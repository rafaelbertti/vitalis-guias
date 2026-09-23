from datetime import date
from decimal import Decimal

from vitalis.normalizacao import normalizar_data, normalizar_valor, normalizar_inteiro, normalizar_guia


def test_data_iso_fica_como_esta():
    assert normalizar_data("2026-08-03") == (date(2026, 8, 3), None)


def test_data_brasileira_e_normalizada_com_aviso():
    assert normalizar_data("03/08/2026") == (date(2026, 8, 3), "normalizada")


def test_data_impossivel_e_invalida():
    assert normalizar_data("2026-13-40") == (None, "invalida")
    assert normalizar_data("31/02/2026") == (None, "invalida")
    assert normalizar_data("ontem") == (None, "invalida")


def test_data_vazia():
    assert normalizar_data("") == (None, "vazia")
    assert normalizar_data(None) == (None, "vazia")


def test_valor_com_ponto_e_com_virgula():
    assert normalizar_valor("62.00") == (Decimal("62.00"), None)
    assert normalizar_valor("62,00") == (Decimal("62.00"), "normalizada")
    assert normalizar_valor("1.234,56") == (Decimal("1234.56"), "normalizada")


def test_valor_invalido_ou_negativo():
    assert normalizar_valor("sessenta") == (None, "invalida")
    assert normalizar_valor("-5") == (None, "invalida")


def test_inteiro():
    assert normalizar_inteiro("7") == (7, None)
    assert normalizar_inteiro("sete") == (None, "invalida")
    assert normalizar_inteiro("") == (None, "vazia")


def test_normalizar_guia_preserva_original_e_avisa():
    g, motivos = normalizar_guia({"id_guia": "X", "data_atendimento": "03/08/2026", "valor": "62,00",
                                  "sessao_numero_na_autorizacao": "3", "autorizacao_sessoes_limite": "10",
                                  "data_lancamento": "2026-08-04", "autorizacao_validade": "2026-08-14"})
    assert g["data_atendimento"] == "03/08/2026"
    assert g["data_atendimento_norm"] == date(2026, 8, 3)
    assert g["valor_norm"] == Decimal("62.00")
    codigos = sorted(m.codigo for m in motivos)
    assert codigos == ["DATA_NORMALIZADA", "VALOR_NORMALIZADO"]
    assert all(m.gravidade == "aviso" for m in motivos)


def test_normalizar_guia_data_invalida_vira_corrigir():
    g, motivos = normalizar_guia({"id_guia": "X", "data_atendimento": "2026-99-99", "valor": "62.00",
                                  "sessao_numero_na_autorizacao": "1", "autorizacao_sessoes_limite": "10"})
    assert g["data_atendimento_norm"] is None
    assert any(m.codigo == "DATA_INVALIDA" and m.gravidade == "corrigir" for m in motivos)
