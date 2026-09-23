"""Normalização dos campos que a recepção digita de jeitos diferentes.

Regra de ouro: normalizar só quando a interpretação é inequívoca (``03/08/2026`` → ``2026-08-03``,
``62,00`` → ``62.00``) e sempre avisar. Nunca "corrigir por adivinhação": data impossível ou valor
ambíguo viram motivo de correção, não um chute.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

COLUNAS = [
    "id_guia", "unidade", "data_atendimento", "paciente", "convenio", "carteirinha", "cid",
    "procedimento_codigo", "procedimento_descricao", "numero_autorizacao", "autorizacao_validade",
    "autorizacao_sessoes_limite", "sessao_numero_na_autorizacao", "profissional",
    "profissional_registro", "valor", "observacao_recepcao", "data_lancamento",
]

# Gravidades, da mais séria para a menos:
#   bloqueia  -> a guia não pode ser enviada nas condições atuais (decisão nao_enviar)
#   corrigir  -> falta informação ou há divergência a resolver antes do envio (decisão corrigir)
#   aviso     -> algo foi normalizado ou merece atenção; não muda a decisão
#   info      -> contexto útil (ex.: vínculo com outra guia); não muda a decisão
GRAVIDADES = ("bloqueia", "corrigir", "aviso", "info")


@dataclass
class Motivo:
    codigo: str
    gravidade: str
    mensagem: str
    campo: Optional[str] = None
    valor: Optional[str] = None
    regra: Optional[str] = None
    correcao: Optional[str] = None
    encaminhamento: Optional[str] = None  # "particular" quando o caminho é faturar fora do convênio

    def __post_init__(self):
        if self.gravidade not in GRAVIDADES:
            raise ValueError(f"gravidade inválida: {self.gravidade}")

    def como_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}


_FORMATOS_DATA = ("%Y-%m-%d", "%d/%m/%Y")


def normalizar_data(texto: Optional[str]) -> tuple[Optional[date], Optional[str]]:
    """Devolve (data, situacao). situacao: None (já estava no padrão), "normalizada", "invalida", "vazia"."""
    if texto is None or not str(texto).strip():
        return None, "vazia"
    s = str(texto).strip()
    for i, fmt in enumerate(_FORMATOS_DATA):
        try:
            d = datetime.strptime(s, fmt).date()
            return d, (None if i == 0 else "normalizada")
        except ValueError:
            continue
    return None, "invalida"


def normalizar_valor(texto: Optional[str]) -> tuple[Optional[Decimal], Optional[str]]:
    """Aceita "62.00" e "62,00". "1.234,56" também. Devolve (Decimal, situacao)."""
    if texto is None or not str(texto).strip():
        return None, "vazia"
    s = str(texto).strip().replace("R$", "").strip()
    normalizada = False
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
        normalizada = True
    try:
        v = Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None, "invalida"
    if v < 0:
        return None, "invalida"
    return v, ("normalizada" if normalizada else None)


def normalizar_inteiro(texto: Optional[str]) -> tuple[Optional[int], Optional[str]]:
    if texto is None or not str(texto).strip():
        return None, "vazia"
    s = str(texto).strip()
    if not re.fullmatch(r"\d+", s):
        return None, "invalida"
    return int(s), None


def normalizar_guia(guia: dict) -> tuple[dict, list[Motivo]]:
    """Copia a guia com os campos tipados em ``_norm`` e devolve os motivos de normalização.

    Campos originais ficam intactos (o original é preservado para auditoria).
    """
    g = {c: ("" if guia.get(c) is None else str(guia.get(c)).strip()) for c in COLUNAS}
    motivos: list[Motivo] = []

    for campo in ("data_atendimento", "autorizacao_validade", "data_lancamento"):
        d, situacao = normalizar_data(g[campo])
        g[f"{campo}_norm"] = d
        if situacao == "normalizada":
            motivos.append(Motivo("DATA_NORMALIZADA", "aviso",
                                  f"{campo} estava como '{g[campo]}' e foi lida como {d.isoformat()}",
                                  campo=campo, valor=g[campo], correcao="Lançar datas como AAAA-MM-DD"))
        elif situacao == "invalida":
            motivos.append(Motivo("DATA_INVALIDA", "corrigir",
                                  f"{campo} '{g[campo]}' não é uma data reconhecível",
                                  campo=campo, valor=g[campo], correcao="Informar a data no formato AAAA-MM-DD"))

    v, situacao = normalizar_valor(g["valor"])
    g["valor_norm"] = v
    if situacao == "normalizada":
        motivos.append(Motivo("VALOR_NORMALIZADO", "aviso",
                              f"valor estava como '{g['valor']}' e foi lido como {v}",
                              campo="valor", valor=g["valor"], correcao="Lançar valor com ponto decimal (62.00)"))
    elif situacao == "invalida":
        motivos.append(Motivo("VALOR_INVALIDO", "corrigir", f"valor '{g['valor']}' não é um número",
                              campo="valor", valor=g["valor"], correcao="Informar o valor em reais (ex.: 62.00)"))
    elif situacao == "vazia":
        motivos.append(Motivo("VALOR_INVALIDO", "corrigir", "valor está vazio",
                              campo="valor", valor="", correcao="Informar o valor em reais (ex.: 62.00)"))

    for campo in ("sessao_numero_na_autorizacao", "autorizacao_sessoes_limite"):
        n, situacao = normalizar_inteiro(g[campo])
        g[f"{campo}_norm"] = n
        if situacao == "invalida":
            motivos.append(Motivo("NUMERO_INVALIDO", "corrigir", f"{campo} '{g[campo]}' não é um número inteiro",
                                  campo=campo, valor=g[campo], correcao="Informar um número inteiro"))

    return g, motivos
