"""Leitura do texto livre da recepção (``observacao_recepcao``).

Política: o motor só entende o que está listado aqui. Observações benignas conhecidas não geram
nada; os padrões de ação geram motivos; **qualquer outro texto** vira ``OBSERVACAO_NAO_INTERPRETADA``
(corrigir), porque liberar uma guia com uma observação que ninguém leu é exatamente o erro que
a clínica quer parar de cometer. Não há LLM aqui: cada padrão é uma expressão regular com teste.
"""

from __future__ import annotations

import re
import unicodedata

from .normalizacao import Motivo


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


# Observações que aparecem no dia a dia e não mudam a conferência.
BENIGNAS = [
    r"paciente chegou \d+ min atrasad",
    r"confirmado pelo whatsapp",
    r"pediu recibo para reembolso",
    r"trouxe exame novo",
]

# Padrões de ação: (codigo, regex, gravidade, mensagem, correcao, encaminhamento)
PADROES = [
    ("AUTORIZACAO_NOVA_NAO_LANCADA",
     r"autorizacao nova.*(ainda nao lancad|nao lancad|numero ainda nao)",
     "corrigir",
     "A recepção anotou autorização nova, mas o número não foi lançado na guia",
     "Lançar o número e a validade da autorização nova e conferir de novo",
     None),
    ("AUTORIZACAO_VERBAL_SEM_NUMERO",
     r"autorizad[oa] por telefone|protocolo\s*\d+",
     "corrigir",
     "Autorização verbal com protocolo; o número da autorização precisa entrar antes do envio",
     "Obter o número da autorização junto ao convênio e lançar na guia",
     None),
    ("PACIENTE_PEDIU_PARTICULAR",
     r"faturar como particular|nao quer usar o convenio",
     "bloqueia",
     "Paciente pediu para faturar como particular; a guia não deve ir ao convênio",
     "Faturar como particular e não enviar ao convênio",
     "particular"),
    ("PROCEDIMENTO_A_CORRIGIR",
     r"lancar o codigo certo|procedimento realizado foi",
     "corrigir",
     "A observação diz que o procedimento realizado não é o lançado",
     "Confirmar o procedimento realizado, corrigir código, cobertura e valor",
     None),
    ("SESSAO_REMARCADA",
     r"remarcad",
     "info",
     "Sessão remarcada; a validade da autorização é conferida contra a data em que o atendimento aconteceu",
     None,
     None),
]

_NEGACAO = re.compile(r"\bnao\b")


def _negado(texto: str, inicio: int) -> bool:
    """True se há um 'não' logo antes do trecho casado, na mesma oração (ex.: 'não trouxe autorização nova')."""
    oracao = re.split(r"[.;]", texto[:inicio])[-1]
    return bool(_NEGACAO.search(oracao[-40:]))


def interpretar_observacao(texto: str | None) -> list[Motivo]:
    if not texto or not texto.strip():
        return []
    original = texto.strip()
    t = _sem_acento(original)

    if any(re.search(p, t) for p in BENIGNAS):
        return []

    motivos: list[Motivo] = []
    for codigo, regex, gravidade, mensagem, correcao, encaminhamento in PADROES:
        m = re.search(regex, t)
        if m and not _negado(t, m.start()):
            motivos.append(Motivo(codigo, gravidade, mensagem, campo="observacao_recepcao",
                                  valor=original, correcao=correcao, encaminhamento=encaminhamento))

    if not motivos:
        motivos.append(Motivo("OBSERVACAO_NAO_INTERPRETADA", "corrigir",
                              "A recepção escreveu algo que o sistema não sabe interpretar; alguém precisa ler",
                              campo="observacao_recepcao", valor=original,
                              correcao="Ler a observação e decidir manualmente"))
    return motivos
