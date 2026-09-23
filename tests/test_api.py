"""Contrato da API: erros de envelope viram 400 com explicação; pendências de negócio vêm na resposta 200."""

import pytest
from fastapi.testclient import TestClient

from app import app

cliente = TestClient(app)

GUIA = {
    "id_guia": "T-API-1", "unidade": "Centro", "data_atendimento": "2026-08-10", "paciente": "P-9999",
    "convenio": "Vitalcard", "carteirinha": "123", "cid": "M54.5", "procedimento_codigo": "50000470",
    "procedimento_descricao": "Sessão de fisioterapia musculoesquelética", "numero_autorizacao": "AUTX",
    "autorizacao_validade": "2026-08-20", "autorizacao_sessoes_limite": "10", "sessao_numero_na_autorizacao": "3",
    "profissional": "Fulana", "profissional_registro": "CREFITO-3 1-F", "valor": "62.00",
    "observacao_recepcao": "", "data_lancamento": "2026-08-11",
}


def test_pagina_abre():
    r = cliente.get("/")
    assert r.status_code == 200 and "Vitalis" in r.text


def test_saude():
    assert cliente.get("/api/saude").json()["guias_no_lote"] == 80


def test_guias_do_lote():
    r = cliente.get("/api/guias").json()
    assert r["total"] == 80
    assert {"id_guia", "resultado"} <= set(r["guias"][0])


def test_relatorio_json_e_markdown():
    rel = cliente.get("/api/relatorio").json()
    assert rel["total_verificadas"] == 80
    assert rel["por_decisao"]["ok"]["guias"] + rel["com_problema"] == 80
    md = cliente.get("/api/relatorio.md").text
    assert md.startswith("# Relatório de terça")


def test_regras_por_par():
    r = cliente.get("/api/regras", params={"convenio": "Plano Bem", "procedimento": "20103301"}).json()
    assert r["coberto"] is False
    assert cliente.get("/api/regras", params={"convenio": "Nao Existe"}).status_code == 404


def test_verificar_guia_ok():
    r = cliente.post("/api/verificar", json=GUIA)
    assert r.status_code == 200
    assert r.json()["decisao"] == "ok"


def test_verificar_guia_com_pendencia_responde_200():
    r = cliente.post("/api/verificar", json={**GUIA, "cid": ""})
    assert r.status_code == 200
    assert r.json()["decisao"] == "corrigir"


def test_verificar_guia_incompleta_e_pendencia_nao_erro():
    r = cliente.post("/api/verificar", json={"id_guia": "SO-ID"})
    assert r.status_code == 200
    assert r.json()["decisao"] == "corrigir"


def test_envelope_com_data_referencia():
    r = cliente.post("/api/verificar", json={"guia": GUIA, "data_referencia": "2026-09-30"})
    assert r.status_code == 200
    assert r.json()["data_referencia"] == "2026-09-30"
    assert r.json()["decisao"] == "nao_enviar"  # prazo de 30 dias estourado em 30/09


def test_coluna_desconhecida_e_400():
    r = cliente.post("/api/verificar", json={**GUIA, "paciente_nome": "x"})
    assert r.status_code == 400
    assert "paciente_nome" in r.json()["detail"]["colunas"]


def test_sem_id_e_400():
    assert cliente.post("/api/verificar", json={**GUIA, "id_guia": ""}).status_code == 400


def test_json_invalido_e_400():
    r = cliente.post("/api/verificar", content="isso nao e json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400


def test_data_referencia_invalida_e_400():
    assert cliente.post("/api/verificar?data_referencia=ontem", json=GUIA).status_code == 400


def test_duplicidade_contra_o_lote():
    # cópia da G-2608-0001 com outro id, lançada depois -> possível duplicidade
    original = next(g for g in cliente.get("/api/guias").json()["guias"] if g["id_guia"] == "G-2608-0001")
    copia = {c: original[c] for c in GUIA}
    copia.update(id_guia="G-2608-9999", data_lancamento="2026-09-01")
    r = cliente.post("/api/verificar", json=copia).json()
    assert r["decisao"] == "corrigir"
    assert any(m["codigo"] == "POSSIVEL_DUPLICIDADE" and m["valor"] == "G-2608-0001" for m in r["motivos"])


def test_lote_csv():
    csv = "id_guia,unidade,data_atendimento,paciente,convenio,carteirinha,cid,procedimento_codigo,procedimento_descricao,numero_autorizacao,autorizacao_validade,autorizacao_sessoes_limite,sessao_numero_na_autorizacao,profissional,profissional_registro,valor,observacao_recepcao,data_lancamento\n" \
          "L-1,Sul,2026-08-10,P-1,Vitalcard,1,M54.5,50000470,Sessão,AUT1,2026-08-20,10,3,F,CREFITO-3 1-F,62.00,,2026-08-11\n" \
          "L-2,Sul,2026-08-10,P-2,Vitalcard,1,M54.5,50000470,Sessão,AUT2,2026-08-01,10,3,F,CREFITO-3 1-F,62.00,,2026-08-11\n"
    r = cliente.post("/api/verificar-lote", content=csv, headers={"Content-Type": "text/csv"})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["total"] == 2
    assert [x["decisao"] for x in corpo["resultados"]] == ["ok", "nao_enviar"]
    assert corpo["relatorio"]["com_problema"] == 1


def test_lote_csv_sem_cabecalho_certo_e_400():
    r = cliente.post("/api/verificar-lote", content="a,b\n1,2\n", headers={"Content-Type": "text/csv"})
    assert r.status_code == 400
    assert cliente.post("/api/verificar-lote", content="", headers={"Content-Type": "text/csv"}).status_code == 400
