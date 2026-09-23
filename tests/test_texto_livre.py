from vitalis.texto_livre import interpretar_observacao


def codigos(texto):
    return [m.codigo for m in interpretar_observacao(texto)]


def test_vazio_nao_gera_nada():
    assert codigos("") == []
    assert codigos(None) == []
    assert codigos("   ") == []


def test_benignas_nao_geram_nada():
    assert codigos("Paciente chegou 10 min atrasado.") == []
    assert codigos("Confirmado pelo WhatsApp na véspera.") == []
    assert codigos("Pediu recibo para reembolso do plano.") == []
    assert codigos("Trouxe exame novo, anexado ao prontuário.") == []


def test_autorizacao_nova_nao_lancada():
    m = interpretar_observacao("Paciente trouxe autorização nova, número ainda não lançado. Validade 30/09.")
    assert [x.codigo for x in m] == ["AUTORIZACAO_NOVA_NAO_LANCADA"]
    assert m[0].gravidade == "corrigir"


def test_autorizacao_verbal_com_protocolo():
    m = interpretar_observacao("Autorizado por telefone, protocolo 771203, aguardando número.")
    assert [x.codigo for x in m] == ["AUTORIZACAO_VERBAL_SEM_NUMERO"]
    assert m[0].gravidade == "corrigir"


def test_remarcada_e_so_informacao():
    m = interpretar_observacao("Sessão remarcada de 12/08 para hoje, autorização era da data original.")
    assert [x.codigo for x in m] == ["SESSAO_REMARCADA"]
    assert m[0].gravidade == "info"


def test_particular_bloqueia_e_encaminha():
    m = interpretar_observacao("Paciente pediu para faturar como particular, não quer usar o convênio.")
    assert [x.codigo for x in m] == ["PACIENTE_PEDIU_PARTICULAR"]
    assert m[0].gravidade == "bloqueia"
    assert m[0].encaminhamento == "particular"


def test_codigo_errado():
    m = interpretar_observacao("Procedimento realizado foi drenagem linfática, lançar o código certo.")
    assert [x.codigo for x in m] == ["PROCEDIMENTO_A_CORRIGIR"]
    assert m[0].gravidade == "corrigir"


def test_texto_desconhecido_vai_para_revisao():
    m = interpretar_observacao("Autorização cancelada pelo convênio ontem.")
    assert [x.codigo for x in m] == ["OBSERVACAO_NAO_INTERPRETADA"]
    assert m[0].gravidade == "corrigir"


def test_negacao_nao_casa_o_padrao():
    # "não trouxe autorização nova" não pode virar AUTORIZACAO_NOVA_NAO_LANCADA
    assert codigos("Paciente não trouxe autorização nova, número ainda não lançado.") == ["OBSERVACAO_NAO_INTERPRETADA"]
    # "não faturar como particular" não pode encaminhar para particular
    assert codigos("Paciente pediu para não faturar como particular.") == ["OBSERVACAO_NAO_INTERPRETADA"]


def test_padroes_sao_insensiveis_a_acento_e_caixa():
    assert codigos("AUTORIZADO POR TELEFONE, PROTOCOLO 1") == ["AUTORIZACAO_VERBAL_SEM_NUMERO"]
    assert codigos("Sessao remarcada.") == ["SESSAO_REMARCADA"]
