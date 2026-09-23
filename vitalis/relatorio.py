"""Relatório de terça do Dr. Renato: quantas guias verificadas, quantas com problema, de que tipo
e quanto dinheiro está em risco. Gerado a partir do mesmo motor da API.

Uso:  python -m vitalis.relatorio [--csv caminho] [--data-referencia AAAA-MM-DD] [--saida relatorio/relatorio_terca.md] [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from .lote import carregar_guias, verificar_lote
from .regras import carregar_regras

ROTULO = {"ok": "OK para enviar", "corrigir": "Corrigir antes de enviar", "nao_enviar": "Não enviar ao convênio"}


def _dec(v) -> Decimal:
    return Decimal(v) if v is not None else Decimal("0")


def _brl(v: Decimal) -> str:
    s = f"{v:,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def montar_relatorio(resultados: list[dict], guias: list[dict], gerado_em: datetime | None = None,
                     data_referencia: date | None = None) -> dict:
    """Cada guia entra uma única vez na sua categoria. Em "por motivo", cada código conta uma vez por guia
    (uma guia com dois campos vazios é 1 em CAMPO_OBRIGATORIO_VAZIO); uma guia pode aparecer em vários códigos."""
    gerado_em = gerado_em or datetime.now()
    por_id = {g["id_guia"]: g for g in guias}
    total = len(resultados)

    por_decisao = {d: {"guias": 0, "valor": Decimal("0")} for d in ROTULO}
    valor_particular = Decimal("0")
    guias_particular = 0
    excesso_duplicidade = Decimal("0")
    por_motivo: Counter = Counter()
    avisos: Counter = Counter()
    def _grupo():
        return {"ok": 0, "corrigir": 0, "nao_enviar": 0, "valor_pendente": Decimal("0"), "valor_particular": Decimal("0")}
    por_unidade: dict = defaultdict(_grupo)
    por_convenio: dict = defaultdict(_grupo)
    acoes = []

    for r in resultados:
        g = por_id.get(r["id_guia"], {})
        valor = _dec(r.get("valor"))
        d = r["decisao"]
        por_decisao[d]["guias"] += 1
        por_decisao[d]["valor"] += valor
        if r["encaminhamento"] == "particular":
            guias_particular += 1
            valor_particular += valor
        codigos = {m["codigo"] for m in r["motivos"]}
        if "POSSIVEL_DUPLICIDADE" in codigos:
            excesso_duplicidade += valor
        graves = {m["codigo"] for m in r["motivos"] if m["gravidade"] in ("bloqueia", "corrigir")}
        for codigo in graves:
            por_motivo[codigo] += 1
        for codigo in codigos - graves:
            avisos[codigo] += 1
        particular = r["encaminhamento"] == "particular"
        for chave, agrupador in ((g.get("unidade", "?"), por_unidade), (g.get("convenio", "?"), por_convenio)):
            agrupador[chave][d] += 1
            if particular:
                agrupador[chave]["valor_particular"] += valor
            elif d != "ok":
                agrupador[chave]["valor_pendente"] += valor
        if d != "ok":
            acoes.append({
                "id_guia": r["id_guia"], "unidade": g.get("unidade"), "convenio": g.get("convenio"),
                "paciente": g.get("paciente"), "valor": str(valor), "decisao": d,
                "encaminhamento": r["encaminhamento"],
                "motivos": [m["codigo"] for m in r["motivos"] if m["gravidade"] in ("bloqueia", "corrigir")],
                "o_que_fazer": r["corrigir"],
            })

    pendente_convenio = por_decisao["corrigir"]["valor"] + por_decisao["nao_enviar"]["valor"] - valor_particular
    com_problema = por_decisao["corrigir"]["guias"] + por_decisao["nao_enviar"]["guias"]

    return {
        "gerado_em": gerado_em.isoformat(timespec="minutes"),
        "referencia": (f"conferência na data {data_referencia.isoformat()}" if data_referencia
                       else "conferência na data de lançamento de cada guia"),
        "total_verificadas": total,
        "com_problema": com_problema,
        "por_decisao": {d: {"rotulo": ROTULO[d], "guias": v["guias"], "valor": str(v["valor"])} for d, v in por_decisao.items()},
        "dinheiro": {
            "valor_verificado": str(sum((_dec(r.get("valor")) for r in resultados), Decimal("0"))),
            "pendente_no_convenio": str(pendente_convenio),
            "explicacao_pendente": "soma das guias em 'corrigir' e 'não enviar' que seguem no convênio; "
                                   "não é glosa confirmada, é o que não deve ser enviado como está",
            "encaminhado_particular": str(valor_particular),
            "guias_particular": guias_particular,
            "excesso_possivel_duplicidade": str(excesso_duplicidade),
        },
        "por_motivo": [{"codigo": c, "guias": n} for c, n in por_motivo.most_common()],
        "avisos": [{"codigo": c, "guias": n} for c, n in avisos.most_common()],
        "por_unidade": {u: {**v, "valor_pendente": str(v["valor_pendente"]), "valor_particular": str(v["valor_particular"])}
                        for u, v in sorted(por_unidade.items())},
        "por_convenio": {c: {**v, "valor_pendente": str(v["valor_pendente"]), "valor_particular": str(v["valor_particular"])}
                         for c, v in sorted(por_convenio.items())},
        "acoes": sorted(acoes, key=lambda a: (a["decisao"] != "nao_enviar", a["id_guia"])),
    }


def relatorio_markdown(rel: dict) -> str:
    L = []
    L.append(f"# Relatório de terça — conferência de guias de convênio\n")
    L.append(f"Gerado em {rel['gerado_em'].replace('T', ' ')} · {rel['referencia']}\n")
    L.append("## Em uma linha\n")
    L.append(f"**{rel['total_verificadas']} guias verificadas, {rel['com_problema']} com problema, "
             f"{_brl(_dec(rel['dinheiro']['pendente_no_convenio']))} que não devem ir ao convênio como estão.**\n")
    L.append("## Resultado\n")
    L.append("| Situação | Guias | Valor |\n|---|---:|---:|")
    for d in ("ok", "corrigir", "nao_enviar"):
        v = rel["por_decisao"][d]
        L.append(f"| {v['rotulo']} | {v['guias']} | {_brl(_dec(v['valor']))} |")
    L.append(f"| **Total** | **{rel['total_verificadas']}** | **{_brl(_dec(rel['dinheiro']['valor_verificado']))}** |\n")
    din = rel["dinheiro"]
    L.append("## Dinheiro\n")
    L.append(f"- **Pendente no convênio:** {_brl(_dec(din['pendente_no_convenio']))} — {din['explicacao_pendente']}.")
    L.append(f"- **Encaminhado para particular:** {_brl(_dec(din['encaminhado_particular']))} em {din['guias_particular']} guia(s) "
             f"(não é perda: é cobrança por outro caminho).")
    L.append(f"- **Possível duplicidade:** dos quais {_brl(_dec(din['excesso_possivel_duplicidade']))} estão em guias que repetem "
             f"outra já lançada (já contados no pendente acima); se confirmado, é excesso a cancelar, não a corrigir.\n")
    L.append("## Por tipo de problema\n")
    L.append("| Motivo | Guias |\n|---|---:|")
    for m in rel["por_motivo"]:
        L.append(f"| {m['codigo']} | {m['guias']} |")
    L.append("\nUma guia pode ter mais de um motivo; a soma desta tabela é maior que o número de guias com problema.\n")
    if rel["avisos"]:
        L.append("Avisos que não mudam a decisão: " + ", ".join(f"{a['codigo']} ({a['guias']})" for a in rel["avisos"]) + "\n")
    for titulo, chave in (("Por unidade", "por_unidade"), ("Por convênio", "por_convenio")):
        L.append(f"## {titulo}\n")
        L.append("| | OK | Corrigir | Não enviar | Pendente no convênio | Particular |\n|---|---:|---:|---:|---:|---:|")
        for nome, v in rel[chave].items():
            L.append(f"| {nome} | {v['ok']} | {v['corrigir']} | {v['nao_enviar']} | {_brl(_dec(v['valor_pendente']))} | {_brl(_dec(v['valor_particular']))} |")
        L.append("")
    L.append("## O que fazer esta semana\n")
    L.append("| Guia | Unidade | Convênio | Valor | Situação | Motivos | O que fazer |\n|---|---|---|---:|---|---|---|")
    for a in rel["acoes"]:
        situacao = ROTULO[a["decisao"]] + (" (particular)" if a["encaminhamento"] == "particular" else "")
        L.append(f"| {a['id_guia']} | {a['unidade']} | {a['convenio']} | {_brl(_dec(a['valor']))} | {situacao} | "
                 f"{', '.join(a['motivos'])} | {' / '.join(a['o_que_fazer'])} |")
    L.append("")
    L.append("---\n*Limite deste relatório:* ele cobre o lote de guias carregado (as 80 de agosto). Guias verificadas "
             "pela API fora do lote não entram aqui; a integração com o sistema de gestão é o próximo passo.\n")
    return "\n".join(L)


def gerar(caminho_csv=None, data_referencia: date | None = None) -> tuple[dict, str]:
    regras = carregar_regras()
    guias = carregar_guias(caminho_csv)
    resultados = verificar_lote(guias, regras, data_referencia=data_referencia)
    rel = montar_relatorio(resultados, guias, data_referencia=data_referencia)
    return rel, relatorio_markdown(rel)


def main(argv=None):
    p = argparse.ArgumentParser(description="Relatório de terça do Dr. Renato")
    p.add_argument("--csv", help="CSV de guias (padrão: vitalis/dados/guias.csv ou GUIAS_CSV)")
    p.add_argument("--data-referencia", help="AAAA-MM-DD; padrão = data de lançamento de cada guia")
    p.add_argument("--saida", default="relatorio/relatorio_terca.md")
    p.add_argument("--json", action="store_true", help="imprime o JSON em vez do Markdown")
    a = p.parse_args(argv)
    dref = date.fromisoformat(a.data_referencia) if a.data_referencia else None
    rel, md = gerar(a.csv, dref)
    if a.json:
        print(json.dumps(rel, ensure_ascii=False, indent=2))
        return
    Path(a.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(a.saida).write_text(md, encoding="utf-8")
    Path(a.saida).with_suffix(".json").write_text(json.dumps(rel, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"relatório salvo em {a.saida} (+ .json)")
    print(md.split("\n")[4])


if __name__ == "__main__":
    main()
