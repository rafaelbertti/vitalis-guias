"""Motor de regras: uma função curta por regra, uma lista ``REGRAS`` e ``verificar_guia``.

Para mudar o comportamento ao vivo: edite a função da regra ou acrescente uma nova função à lista
``REGRAS``. Cada regra recebe a guia normalizada e o contexto e devolve uma lista de ``Motivo``.

Decisão (ver ``decidir``):
  - ``nao_enviar``  se algum motivo ``bloqueia``
  - ``corrigir``    se algum motivo ``corrigir``
  - ``ok``          caso contrário (avisos e infos não mudam a decisão)
Encaminhamento: ``particular`` quando algum motivo diz isso; senão ``convenio``.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from .normalizacao import Motivo, normalizar_guia, normalizar_data
from .texto_livre import interpretar_observacao

VERSAO_MOTOR = "2026-09-23.1"
_AQUI = Path(__file__).resolve().parent
CAMINHO_REGRAS_PADRAO = _AQUI / "dados" / "regras_convenio.json"

# Convênio + procedimento que, pela observação do próprio convênio, não vão como guia de convênio
# e sim como particular. Hoje só o Plano Bem: "Não cobre consulta médica; consulta é faturada como particular."
ENCAMINHAMENTO_PARTICULAR = {("Plano Bem", "20103301")}

# Aviso quando faltam poucos dias para o prazo de envio.
DIAS_ALERTA_PRAZO = 7


def carregar_regras(caminho: str | os.PathLike | None = None) -> dict:
    caminho = Path(caminho or os.environ.get("REGRAS_JSON") or CAMINHO_REGRAS_PADRAO)
    with open(caminho, encoding="utf-8") as f:
        regras = json.load(f)
    regras["_convenios"] = {c["nome"]: c for c in regras["convenios"]}
    regras["_procedimentos"] = {p["codigo"]: p for p in regras["procedimentos"]}
    return regras


@dataclass
class Contexto:
    regras: dict
    data_referencia: date
    outras_guias: list[dict] = field(default_factory=list)
    convenio: Optional[dict] = None
    procedimento: Optional[dict] = None
    observacao: list[Motivo] = field(default_factory=list)

    def tem(self, codigo: str) -> bool:
        return any(m.codigo == codigo for m in self.observacao)


# ----------------------------------------------------------------------------- regras

def regra_convenio_conhecido(g: dict, ctx: Contexto) -> list[Motivo]:
    if ctx.convenio is None:
        nomes = ", ".join(ctx.regras["_convenios"])
        return [Motivo("CONVENIO_DESCONHECIDO", "corrigir",
                       f"Convênio '{g['convenio']}' não está nas regras (conhecidos: {nomes})",
                       campo="convenio", valor=g["convenio"], correcao="Conferir o nome do convênio na guia")]
    return []


def regra_procedimento_conhecido(g: dict, ctx: Contexto) -> list[Motivo]:
    if ctx.procedimento is None:
        return [Motivo("PROCEDIMENTO_DESCONHECIDO", "corrigir",
                       f"Procedimento '{g['procedimento_codigo']}' não está na tabela de procedimentos",
                       campo="procedimento_codigo", valor=g["procedimento_codigo"],
                       correcao="Conferir o código do procedimento na tabela do convênio")]
    return []


def regra_campos_obrigatorios(g: dict, ctx: Contexto) -> list[Motivo]:
    if ctx.convenio is None:
        return []
    motivos = []
    for campo in ctx.convenio["campos_obrigatorios"]:
        if not g.get(campo, "").strip():
            motivos.append(Motivo("CAMPO_OBRIGATORIO_VAZIO", "corrigir",
                                  f"{ctx.convenio['nome']} exige '{campo}' e a guia está sem",
                                  campo=campo, valor="", regra="campos_obrigatorios",
                                  correcao=f"Preencher '{campo}' antes do envio"))
    return motivos


def regra_procedimento_coberto(g: dict, ctx: Contexto) -> list[Motivo]:
    if ctx.convenio is None or ctx.procedimento is None:
        return []
    codigo = g["procedimento_codigo"]
    if codigo in ctx.convenio["procedimentos_cobertos"]:
        return []
    if (ctx.convenio["nome"], codigo) in ENCAMINHAMENTO_PARTICULAR:
        return [Motivo("CONSULTA_FATURADA_PARTICULAR", "bloqueia",
                       f"{ctx.convenio['nome']} não cobre {ctx.procedimento['descricao'].lower()}; "
                       f"pela regra do convênio ela é faturada como particular",
                       campo="procedimento_codigo", valor=codigo, regra="observacao do convenio",
                       correcao="Não enviar ao convênio; faturar como particular", encaminhamento="particular")]
    return [Motivo("PROCEDIMENTO_NAO_COBERTO", "bloqueia",
                   f"{ctx.convenio['nome']} não cobre {ctx.procedimento['descricao'].lower()} ({codigo})",
                   campo="procedimento_codigo", valor=codigo, regra="procedimentos_cobertos",
                   correcao="Conferir com o convênio; se não houver cobertura, combinar outra forma de cobrança")]


def regra_autorizacao_vigente(g: dict, ctx: Contexto) -> list[Motivo]:
    atendimento, validade = g["data_atendimento_norm"], g["autorizacao_validade_norm"]
    if atendimento is None or validade is None:
        return []
    if atendimento <= validade:
        return []
    if ctx.tem("AUTORIZACAO_NOVA_NAO_LANCADA"):
        return [Motivo("AUTORIZACAO_VENCIDA", "corrigir",
                       f"Autorização venceu em {validade.isoformat()} e o atendimento foi em {atendimento.isoformat()}; "
                       f"a recepção anotou autorização nova ainda não lançada",
                       campo="autorizacao_validade", valor=validade.isoformat(), regra="autorizacao_valida",
                       correcao="Lançar a autorização nova (número e validade) e conferir de novo")]
    return [Motivo("AUTORIZACAO_VENCIDA", "bloqueia",
                   f"Autorização venceu em {validade.isoformat()} e o atendimento foi em {atendimento.isoformat()}",
                   campo="autorizacao_validade", valor=validade.isoformat(), regra="autorizacao_valida",
                   correcao="Obter nova autorização junto ao convênio antes de enviar")]


def regra_sessao_no_limite(g: dict, ctx: Contexto) -> list[Motivo]:
    if ctx.convenio is None:
        return []
    motivos = []
    n, limite_csv = g["sessao_numero_na_autorizacao_norm"], g["autorizacao_sessoes_limite_norm"]
    limite = ctx.convenio["limite_sessoes_por_autorizacao"]
    if n is not None:
        if n < 1:
            motivos.append(Motivo("NUMERO_INVALIDO", "corrigir", "sessao_numero_na_autorizacao precisa ser 1 ou mais",
                                  campo="sessao_numero_na_autorizacao", valor=str(n)))
        elif n > limite:
            motivos.append(Motivo("SESSAO_ACIMA_LIMITE", "bloqueia",
                                  f"Sessão {n} de uma autorização que cobre no máximo {limite} ({ctx.convenio['nome']})",
                                  campo="sessao_numero_na_autorizacao", valor=str(n),
                                  regra="limite_sessoes_por_autorizacao",
                                  correcao="Conferir a contagem de sessões; acima do limite é preciso nova autorização"))
    if limite_csv is not None and limite_csv != limite:
        motivos.append(Motivo("LIMITE_SESSOES_DIVERGE", "corrigir",
                              f"A guia diz que a autorização cobre {limite_csv} sessões, a regra do convênio diz {limite}",
                              campo="autorizacao_sessoes_limite", valor=str(limite_csv),
                              regra="limite_sessoes_por_autorizacao", correcao="Conferir o limite da autorização"))
    return motivos


def regra_prazo_envio(g: dict, ctx: Contexto) -> list[Motivo]:
    if ctx.convenio is None or g["data_atendimento_norm"] is None:
        return []
    atendimento, lancamento = g["data_atendimento_norm"], g["data_lancamento_norm"]
    motivos = []
    if lancamento is not None and lancamento < atendimento:
        motivos.append(Motivo("LANCAMENTO_ANTES_DO_ATENDIMENTO", "corrigir",
                              f"Lançada em {lancamento.isoformat()}, antes do atendimento em {atendimento.isoformat()}",
                              campo="data_lancamento", valor=lancamento.isoformat(),
                              correcao="Conferir as datas de atendimento e lançamento"))
    prazo = ctx.convenio["prazo_envio_dias"]
    dias_passados = (ctx.data_referencia - atendimento).days
    restantes = prazo - dias_passados
    if restantes < 0:
        motivos.append(Motivo("PRAZO_ENVIO_VENCIDO", "bloqueia",
                              f"{ctx.convenio['nome']} aceita guias até {prazo} dias após o atendimento; "
                              f"em {ctx.data_referencia.isoformat()} já se passaram {dias_passados}",
                              campo="data_atendimento", valor=atendimento.isoformat(), regra="prazo_envio_dias",
                              correcao="Prazo de envio esgotado; verificar com o convênio se há recurso"))
    elif restantes <= DIAS_ALERTA_PRAZO:
        motivos.append(Motivo("PRAZO_ENVIO_PROXIMO", "aviso",
                              f"Faltam {restantes} dia(s) para o prazo de envio ({prazo} dias após o atendimento)",
                              campo="data_atendimento", valor=atendimento.isoformat(), regra="prazo_envio_dias",
                              correcao="Enviar esta guia primeiro"))
    return motivos


def regra_valor_referencia(g: dict, ctx: Contexto) -> list[Motivo]:
    if ctx.procedimento is None or g["valor_norm"] is None:
        return []
    ref = ctx.procedimento["valor_referencia"]
    if float(g["valor_norm"]) != float(ref):
        return [Motivo("VALOR_DIVERGE_REFERENCIA", "corrigir",
                       f"Valor lançado {g['valor_norm']} difere do valor de referência {ref:.2f}",
                       campo="valor", valor=str(g["valor_norm"]), regra="valor_referencia",
                       correcao=f"Conferir o valor; a referência do procedimento é {ref:.2f}")]
    return []


def regra_observacao(g: dict, ctx: Contexto) -> list[Motivo]:
    return list(ctx.observacao)


def _chave_duplicidade(g: dict) -> tuple:
    d = g.get("data_atendimento_norm") or normalizar_data(g.get("data_atendimento"))[0]
    return (g.get("convenio", "").strip(), g.get("paciente", "").strip(), d,
            g.get("procedimento_codigo", "").strip(), g.get("numero_autorizacao", "").strip())


def _ordem(g: dict) -> tuple:
    d = g.get("data_lancamento_norm") or normalizar_data(g.get("data_lancamento"))[0]
    return (d or date.max, g.get("id_guia", ""))


def regra_duplicidade(g: dict, ctx: Contexto) -> list[Motivo]:
    """Compara com as outras guias do contexto. A anterior (menor data de lançamento, depois id) é
    preservada; a posterior fica pendente de confirmação. Mesmo id não conta (reprocessamento)."""
    if not ctx.outras_guias or not g["numero_autorizacao"]:
        return []
    chave = _chave_duplicidade(g)
    iguais = [o for o in ctx.outras_guias
              if o.get("id_guia") != g["id_guia"] and _chave_duplicidade(o) == chave]
    if not iguais:
        return []
    anteriores = [o for o in iguais if _ordem(o) < _ordem(g)]
    if anteriores:
        primeira = min(anteriores, key=_ordem)
        return [Motivo("POSSIVEL_DUPLICIDADE", "corrigir",
                       f"Mesmo paciente, data, procedimento e autorização da guia {primeira['id_guia']}, lançada antes",
                       campo="id_guia", valor=primeira["id_guia"], regra="duplicidade",
                       correcao=f"Confirmar se é a mesma sessão da guia {primeira['id_guia']}; se for, cancelar esta")]
    ids = ", ".join(sorted(o["id_guia"] for o in iguais))
    return [Motivo("TEM_POSSIVEL_DUPLICATA", "info",
                   f"Guia(s) {ids} repetem esta sessão e foram lançadas depois; esta é a original",
                   campo="id_guia", valor=ids, regra="duplicidade")]


REGRAS: list[Callable[[dict, Contexto], list[Motivo]]] = [
    regra_convenio_conhecido,
    regra_procedimento_conhecido,
    regra_campos_obrigatorios,
    regra_procedimento_coberto,
    regra_autorizacao_vigente,
    regra_sessao_no_limite,
    regra_prazo_envio,
    regra_valor_referencia,
    regra_observacao,
    regra_duplicidade,
]

_PESO = {"bloqueia": 0, "corrigir": 1, "aviso": 2, "info": 3}


def decidir(motivos: list[Motivo]) -> tuple[str, str]:
    gravidades = {m.gravidade for m in motivos}
    if "bloqueia" in gravidades:
        decisao = "nao_enviar"
    elif "corrigir" in gravidades:
        decisao = "corrigir"
    else:
        decisao = "ok"
    encaminhamento = "particular" if any(m.encaminhamento == "particular" for m in motivos) else "convenio"
    return decisao, encaminhamento


def verificar_guia(guia: dict, regras: dict, contexto: list[dict] | None = None,
                   data_referencia: date | None = None) -> dict:
    """Verifica uma guia (dict com as colunas do CSV) e devolve a decisão com os motivos.

    ``data_referencia``: dia em que a conferência acontece. Se não vier, usa a data de lançamento da
    guia (é o que a clínica faz no lote de agosto); se a guia não tiver lançamento, usa hoje.
    ``contexto``: outras guias (para duplicidade). A própria guia pode estar no contexto.
    """
    g, motivos = normalizar_guia(guia)
    if data_referencia is None:
        data_referencia = g["data_lancamento_norm"] or date.today()
    ctx = Contexto(
        regras=regras,
        data_referencia=data_referencia,
        outras_guias=contexto or [],
        convenio=regras["_convenios"].get(g["convenio"]),
        procedimento=regras["_procedimentos"].get(g["procedimento_codigo"]),
        observacao=interpretar_observacao(g["observacao_recepcao"]),
    )
    for regra in REGRAS:
        motivos.extend(regra(g, ctx))
    motivos.sort(key=lambda m: _PESO[m.gravidade])
    decisao, encaminhamento = decidir(motivos)
    return {
        "id_guia": g["id_guia"],
        "decisao": decisao,
        "encaminhamento": encaminhamento,
        "motivos": [m.como_dict() for m in motivos],
        "corrigir": [m.correcao for m in motivos if m.gravidade in ("bloqueia", "corrigir") and m.correcao],
        "valor": str(g["valor_norm"]) if g["valor_norm"] is not None else None,
        "data_referencia": data_referencia.isoformat(),
        "versao_regras": f"{regras.get('versao', '?')} / motor {VERSAO_MOTOR}",
    }
