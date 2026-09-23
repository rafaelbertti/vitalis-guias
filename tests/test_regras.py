"""Testes por regra, com guias inventadas. Cada teste diz qual regra está cobrindo."""

from datetime import date

import pytest

from vitalis.regras import carregar_regras, verificar_guia


@pytest.fixture(scope="module")
def regras():
    return carregar_regras()


def guia(**campos):
    """Guia Vitalcard válida por padrão; sobrescreva o que o teste precisa."""
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


def codigos(resultado):
    return [m["codigo"] for m in resultado["motivos"]]


def test_guia_valida_e_ok(regras):
    r = verificar_guia(guia(), regras)
    assert r["decisao"] == "ok"
    assert r["encaminhamento"] == "convenio"
    assert r["motivos"] == []
    assert r["data_referencia"] == "2026-08-11"  # data de lançamento por padrão


# --- campos obrigatórios (por convênio)

def test_vitalcard_exige_cid(regras):
    r = verificar_guia(guia(cid=""), regras)
    assert r["decisao"] == "corrigir"
    assert codigos(r) == ["CAMPO_OBRIGATORIO_VAZIO"]
    assert r["motivos"][0]["campo"] == "cid"


def test_saude_interior_nao_exige_cid(regras):
    r = verificar_guia(guia(convenio="Saúde Interior", cid="", autorizacao_sessoes_limite="20"), regras)
    assert r["decisao"] == "ok"


def test_registro_profissional_vazio(regras):
    r = verificar_guia(guia(profissional_registro=""), regras)
    assert r["decisao"] == "corrigir"
    assert r["motivos"][0]["campo"] == "profissional_registro"


# --- cobertura

def test_vitalcard_nao_cobre_infiltracao(regras):
    r = verificar_guia(guia(procedimento_codigo="40201015", valor="140.00"), regras)
    assert r["decisao"] == "nao_enviar"
    assert r["encaminhamento"] == "convenio"
    assert "PROCEDIMENTO_NAO_COBERTO" in codigos(r)


def test_plano_bem_consulta_vai_como_particular(regras):
    r = verificar_guia(guia(convenio="Plano Bem", procedimento_codigo="20103301", valor="90.00",
                            autorizacao_sessoes_limite="12"), regras)
    assert r["decisao"] == "nao_enviar"
    assert r["encaminhamento"] == "particular"
    assert codigos(r) == ["CONSULTA_FATURADA_PARTICULAR"]


def test_procedimento_desconhecido_nao_vira_particular(regras):
    r = verificar_guia(guia(procedimento_codigo="99999999"), regras)
    assert r["decisao"] == "corrigir"
    assert r["encaminhamento"] == "convenio"
    assert codigos(r) == ["PROCEDIMENTO_DESCONHECIDO"]


def test_convenio_desconhecido(regras):
    r = verificar_guia(guia(convenio="Plano Inexistente"), regras)
    assert r["decisao"] == "corrigir"
    assert codigos(r) == ["CONVENIO_DESCONHECIDO"]


# --- validade da autorização (inclusive)

def test_atendimento_no_ultimo_dia_da_validade_e_ok(regras):
    r = verificar_guia(guia(data_atendimento="2026-08-20", autorizacao_validade="2026-08-20",
                            data_lancamento="2026-08-20"), regras)
    assert r["decisao"] == "ok"


def test_atendimento_um_dia_depois_da_validade_bloqueia(regras):
    r = verificar_guia(guia(data_atendimento="2026-08-21", autorizacao_validade="2026-08-20",
                            data_lancamento="2026-08-21"), regras)
    assert r["decisao"] == "nao_enviar"
    assert codigos(r) == ["AUTORIZACAO_VENCIDA"]


def test_vencida_com_autorizacao_nova_anotada_vira_corrigir(regras):
    r = verificar_guia(guia(data_atendimento="2026-08-21", autorizacao_validade="2026-08-20",
                            data_lancamento="2026-08-21",
                            observacao_recepcao="Paciente trouxe autorização nova, número ainda não lançado."), regras)
    assert r["decisao"] == "corrigir"
    assert set(codigos(r)) == {"AUTORIZACAO_VENCIDA", "AUTORIZACAO_NOVA_NAO_LANCADA"}


# --- limite de sessões

def test_sessao_no_limite_e_ok(regras):
    assert verificar_guia(guia(sessao_numero_na_autorizacao="10"), regras)["decisao"] == "ok"


def test_sessao_acima_do_limite_bloqueia(regras):
    r = verificar_guia(guia(sessao_numero_na_autorizacao="11"), regras)
    assert r["decisao"] == "nao_enviar"
    assert codigos(r) == ["SESSAO_ACIMA_LIMITE"]


def test_limite_da_guia_diferente_da_regra(regras):
    r = verificar_guia(guia(autorizacao_sessoes_limite="12"), regras)
    assert r["decisao"] == "corrigir"
    assert codigos(r) == ["LIMITE_SESSOES_DIVERGE"]


# --- prazo de envio (contado do atendimento até a data de referência)

def test_prazo_no_limite_e_ok_com_aviso(regras):
    r = verificar_guia(guia(data_atendimento="2026-08-01", autorizacao_validade="2026-09-30"),
                       regras, data_referencia=date(2026, 8, 31))
    assert r["decisao"] == "ok"
    assert codigos(r) == ["PRAZO_ENVIO_PROXIMO"]


def test_prazo_estourado_bloqueia(regras):
    r = verificar_guia(guia(data_atendimento="2026-08-01", autorizacao_validade="2026-09-30"),
                       regras, data_referencia=date(2026, 9, 1))
    assert r["decisao"] == "nao_enviar"
    assert codigos(r) == ["PRAZO_ENVIO_VENCIDO"]


def test_lancamento_antes_do_atendimento(regras):
    r = verificar_guia(guia(data_atendimento="2026-08-10", data_lancamento="2026-08-09"), regras)
    assert r["decisao"] == "corrigir"
    assert codigos(r) == ["LANCAMENTO_ANTES_DO_ATENDIMENTO"]


# --- valor e formatos

def test_valor_diverge_da_referencia(regras):
    r = verificar_guia(guia(valor="70.00"), regras)
    assert r["decisao"] == "corrigir"
    assert codigos(r) == ["VALOR_DIVERGE_REFERENCIA"]


def test_valor_com_virgula_e_data_brasileira_so_avisam(regras):
    r = verificar_guia(guia(valor="62,00", data_atendimento="10/08/2026"), regras)
    assert r["decisao"] == "ok"
    assert set(codigos(r)) == {"DATA_NORMALIZADA", "VALOR_NORMALIZADO"}


def test_data_invalida_pede_correcao(regras):
    r = verificar_guia(guia(data_atendimento="2026-02-30"), regras)
    assert r["decisao"] == "corrigir"
    assert "DATA_INVALIDA" in codigos(r)


# --- texto livre dentro da decisão

def test_particular_por_pedido_do_paciente(regras):
    r = verificar_guia(guia(observacao_recepcao="Paciente pediu para faturar como particular."), regras)
    assert r["decisao"] == "nao_enviar"
    assert r["encaminhamento"] == "particular"


def test_observacao_desconhecida_nao_libera(regras):
    r = verificar_guia(guia(observacao_recepcao="Convênio ligou dizendo que cancelou a autorização."), regras)
    assert r["decisao"] == "corrigir"
    assert codigos(r) == ["OBSERVACAO_NAO_INTERPRETADA"]


# --- duplicidade (precisa de contexto)

def test_duplicidade_preserva_a_anterior(regras):
    a = guia(id_guia="A", data_lancamento="2026-08-11")
    b = guia(id_guia="B", data_lancamento="2026-08-12")
    ra = verificar_guia(a, regras, contexto=[a, b])
    rb = verificar_guia(b, regras, contexto=[a, b])
    assert ra["decisao"] == "ok" and codigos(ra) == ["TEM_POSSIVEL_DUPLICATA"]
    assert rb["decisao"] == "corrigir" and codigos(rb) == ["POSSIVEL_DUPLICIDADE"]
    assert rb["motivos"][0]["valor"] == "A"


def test_duplicidade_com_data_brasileira_e_ordem_trocada(regras):
    a = guia(id_guia="A", data_atendimento="10/08/2026", data_lancamento="2026-08-11")
    b = guia(id_guia="B", data_lancamento="2026-08-12")
    rb = verificar_guia(b, regras, contexto=[b, a])  # ordem do lote não importa
    assert rb["decisao"] == "corrigir" and "POSSIVEL_DUPLICIDADE" in codigos(rb)


def test_duplicidade_desempata_por_id_quando_lancamento_igual(regras):
    a = guia(id_guia="A"); b = guia(id_guia="B")
    assert verificar_guia(a, regras, contexto=[a, b])["decisao"] == "ok"
    assert verificar_guia(b, regras, contexto=[a, b])["decisao"] == "corrigir"


def test_mesmo_id_no_contexto_e_reprocessamento(regras):
    a = guia(id_guia="A")
    r = verificar_guia(a, regras, contexto=[a])
    assert r["decisao"] == "ok" and r["motivos"] == []


def test_resposta_traz_data_e_versao(regras):
    r = verificar_guia(guia(), regras, data_referencia=date(2026, 8, 15))
    assert r["data_referencia"] == "2026-08-15"
    assert "motor" in r["versao_regras"]
