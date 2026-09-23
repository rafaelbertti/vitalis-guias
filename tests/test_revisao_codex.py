"""Casos levantados na revisão de código do Codex (23/set, commit 547a40e). Cada teste cita o achado."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import app
from vitalis.lote import ler_csv, verificar_lote
from vitalis.regras import carregar_regras, verificar_guia
from vitalis.relatorio import montar_relatorio
from vitalis.texto_livre import interpretar_observacao

cliente = TestClient(app)


@pytest.fixture(scope="module")
def regras():
    return carregar_regras()


def guia(**campos):
    base = dict(
        id_guia="T-0001", unidade="Centro", data_atendimento="2026-08-10", paciente="P-9999",
        convenio="Vitalcard", carteirinha="123456789", cid="M54.5", procedimento_codigo="50000470",
        procedimento_descricao="Sessão de fisioterapia musculoesquelética", numero_autorizacao="AUT1",
        autorizacao_validade="2026-08-20", autorizacao_sessoes_limite="10", sessao_numero_na_autorizacao="3",
        profissional="Fulana", profissional_registro="CREFITO-3 1-F", valor="62.00",
        observacao_recepcao="", data_lancamento="2026-08-11",
    )
    base.update(campos)
    return base


def codigos(r):
    return [m["codigo"] for m in r["motivos"]]


# ---------------------------------------------------------------- R1: observação composta

def test_r1_benigna_mais_particular_prevalece_o_particular(regras):
    r = verificar_guia(guia(observacao_recepcao="Trouxe exame novo. Paciente pediu para faturar como particular."), regras)
    assert r["decisao"] == "nao_enviar" and r["encaminhamento"] == "particular"


def test_r1_benigna_mais_texto_desconhecido_nao_libera(regras):
    r = verificar_guia(guia(observacao_recepcao="Confirmado pelo WhatsApp. Autorização cancelada pelo convênio."), regras)
    assert r["decisao"] == "corrigir"
    assert "OBSERVACAO_NAO_INTERPRETADA" in codigos(r)


def test_r1_info_mais_texto_desconhecido_nao_libera(regras):
    r = verificar_guia(guia(observacao_recepcao="Sessão remarcada. Autorização cancelada pelo convênio."), regras)
    assert r["decisao"] == "corrigir"
    assert {"SESSAO_REMARCADA", "OBSERVACAO_NAO_INTERPRETADA"} <= set(codigos(r))


def test_r1_ordem_invertida_e_negacao():
    c = [m.codigo for m in interpretar_observacao("Paciente pediu para faturar como particular. Trouxe exame novo.")]
    assert c == ["PACIENTE_PEDIU_PARTICULAR"]
    c = [m.codigo for m in interpretar_observacao("Trouxe exame novo. Paciente não quer faturar como particular.")]
    assert c == ["OBSERVACAO_NAO_INTERPRETADA"]


def test_r1_caso_real_0030_continua_interpretado():
    c = [m.codigo for m in interpretar_observacao("Paciente trouxe autorização nova, número ainda não lançado. Validade 30/09.")]
    assert c == ["AUTORIZACAO_NOVA_NAO_LANCADA"]


# ---------------------------------------------------------------- R2: campos necessários vazios

@pytest.mark.parametrize("campo", ["data_atendimento", "sessao_numero_na_autorizacao", "autorizacao_sessoes_limite",
                                   "paciente", "autorizacao_validade", "valor", "convenio", "procedimento_codigo",
                                   "unidade", "data_lancamento"])
@pytest.mark.parametrize("vazio", ["", "   ", None])
def test_r2_campo_necessario_vazio_nao_e_ok(regras, campo, vazio):
    r = verificar_guia(guia(**{campo: vazio}), regras)
    assert r["decisao"] != "ok", f"{campo}={vazio!r} liberou a guia"
    assert any(m["campo"] == campo and m["gravidade"] == "corrigir" for m in r["motivos"])


def test_r2_chave_ausente_no_json_tambem_e_pendencia():
    g = guia(); del g["data_atendimento"]
    r = cliente.post("/api/verificar", json=g)
    assert r.status_code == 200 and r.json()["decisao"] == "corrigir"


# ---------------------------------------------------------------- R3: id repetido no lote

CABECALHO = "id_guia,unidade,data_atendimento,paciente,convenio,carteirinha,cid,procedimento_codigo,procedimento_descricao,numero_autorizacao,autorizacao_validade,autorizacao_sessoes_limite,sessao_numero_na_autorizacao,profissional,profissional_registro,valor,observacao_recepcao,data_lancamento\n"
LINHA = "L-1,Sul,2026-08-10,P-1,Vitalcard,1,M54.5,50000470,Sessão,AUT1,2026-08-20,10,3,F,CREFITO-3 1-F,62.00,,2026-08-11\n"


def test_r3_id_repetido_no_csv_e_rejeitado():
    with pytest.raises(ValueError, match="L-1"):
        ler_csv(CABECALHO + LINHA + LINHA)
    r = cliente.post("/api/verificar-lote", content=CABECALHO + LINHA + LINHA, headers={"Content-Type": "text/csv"})
    assert r.status_code == 400 and "L-1" in str(r.json()["detail"])


def test_r3_lote_base_nao_tem_id_repetido():
    ids = [g["id_guia"] for g in cliente.get("/api/guias").json()["guias"]]
    assert len(ids) == len(set(ids)) == 80


# ---------------------------------------------------------------- R4: envelope inválido

def test_r4_id_null_e_400():
    assert cliente.post("/api/verificar", json={**guia(), "id_guia": None}).status_code == 400


def test_r4_data_referencia_numerica_e_400():
    r = cliente.post("/api/verificar", json={"guia": guia(), "data_referencia": 20260923})
    assert r.status_code == 400


def test_r4_campo_com_objeto_e_400():
    assert cliente.post("/api/verificar", json={**guia(), "paciente": {"nome": "x"}}).status_code == 400


def test_r4_valor_nan_e_pendencia_de_negocio(regras):
    r = verificar_guia(guia(valor="NaN"), regras)
    assert r["decisao"] == "corrigir" and "VALOR_INVALIDO" in codigos(r)
    assert cliente.post("/api/verificar", json={**guia(), "valor": "NaN"}).status_code == 200


def test_r4_valor_infinito_tambem(regras):
    r = verificar_guia(guia(valor="Infinity"), regras)
    assert "VALOR_INVALIDO" in codigos(r)


# ---------------------------------------------------------------- R5: métricas

def test_r5_por_motivo_conta_guias_nao_ocorrencias(regras):
    g = guia(cid="", profissional_registro="")
    res = verificar_lote([g], regras)
    rel = montar_relatorio(res, [g])
    assert rel["por_motivo"] == [{"codigo": "CAMPO_OBRIGATORIO_VAZIO", "guias": 1}]


def test_r5_grupos_batem_com_o_pendente_no_convenio():
    rel = cliente.get("/api/relatorio").json()
    from decimal import Decimal
    soma_unidades = sum(Decimal(v["valor_pendente"]) for v in rel["por_unidade"].values())
    soma_convenios = sum(Decimal(v["valor_pendente"]) for v in rel["por_convenio"].values())
    assert soma_unidades == soma_convenios == Decimal(rel["dinheiro"]["pendente_no_convenio"])
    soma_part = sum(Decimal(v["valor_particular"]) for v in rel["por_unidade"].values())
    assert soma_part == Decimal(rel["dinheiro"]["encaminhado_particular"])


def test_r5_markdown_diz_que_duplicidade_esta_dentro_do_pendente():
    md = cliente.get("/api/relatorio.md").text
    assert "dos quais" in md


# ---------------------------------------------------------------- R6: data de referência

def test_r6b_lote_com_data_referencia_propaga_para_o_relatorio():
    r = cliente.post("/api/verificar-lote?data_referencia=2026-09-23", content=CABECALHO + LINHA,
                     headers={"Content-Type": "text/csv"}).json()
    assert r["resultados"][0]["decisao"] == "nao_enviar"
    assert "2026-09-23" in r["relatorio"]["referencia"]


def test_r6a_pagina_oferece_modo_de_referencia():
    html = cliente.get("/").text
    assert 'name="modo_referencia"' in html
