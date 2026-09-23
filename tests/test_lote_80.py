"""As 80 guias de agosto contra o oráculo escrito à mão em tests/esperado_80.csv.

O oráculo foi montado a partir da análise prévia lida guia a guia, não gerado pelo motor.
Se uma regra mudar de propósito, o oráculo muda junto, conscientemente.
"""

import csv
from pathlib import Path

import pytest

from vitalis.lote import carregar_guias, verificar_lote
from vitalis.regras import carregar_regras

ESPERADO = Path(__file__).parent / "esperado_80.csv"


def _esperado():
    with open(ESPERADO, encoding="utf-8") as f:
        return {r["id_guia"]: r for r in csv.DictReader(f)}


@pytest.fixture(scope="module")
def resultados():
    guias = carregar_guias()
    assert len(guias) == 80
    return {r["id_guia"]: r for r in verificar_lote(guias, carregar_regras())}


@pytest.mark.parametrize("id_guia", sorted(_esperado()))
def test_decisao_da_guia(resultados, id_guia):
    esperado = _esperado()[id_guia]
    r = resultados[id_guia]
    assert r["decisao"] == esperado["decisao"], f"{id_guia}: {esperado['por_que']} | motivos={[m['codigo'] for m in r['motivos']]}"
    assert r["encaminhamento"] == esperado["encaminhamento"]
    obtidos = {m["codigo"] for m in r["motivos"]}
    esperados = {c for c in esperado["motivos_principais"].split(";") if c}
    assert esperados <= obtidos, f"{id_guia}: faltou {esperados - obtidos}; obtidos={obtidos}"
    if not esperados:
        assert obtidos == set(), f"{id_guia}: motivos inesperados {obtidos}"


def test_totais(resultados):
    contagem = {}
    for r in resultados.values():
        contagem[r["decisao"]] = contagem.get(r["decisao"], 0) + 1
    assert contagem == {"ok": 46, "corrigir": 11, "nao_enviar": 23}
