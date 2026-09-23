"""Leitura do texto livre da recepção (``observacao_recepcao``).

Política: o motor só entende o que está listado aqui, **frase por frase**. Cada frase (separada por
ponto ou ponto e vírgula) precisa ser coberta por algo desta lista: uma observação benigna conhecida,
um complemento reconhecido ou um padrão de ação. Frase que sobra sem cobertura vira
``OBSERVACAO_NAO_INTERPRETADA`` (corrigir), porque liberar uma guia com uma observação que ninguém
leu é exatamente o erro que a clínica quer parar de cometer. Não há LLM aqui: cada padrão é uma
expressão regular com teste.
"""

from __future__ import annotations

import re
import unicodedata

from .normalizacao import Motivo


def _sem_acento(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn").lower()


# Frases do dia a dia que não mudam a conferência.
BENIGNAS = [
    r"paciente chegou \d+ min atrasad",
    r"confirmado pelo whatsapp",
    r"pediu recibo para reembolso",
    r"trouxe exame novo",
]

# Frases que só complementam um padrão de ação (ex.: "Validade 30/09." depois de "autorização nova").
COMPLEMENTOS = [
    r"^validade \d{1,2}/\d{1,2}(/\d{2,4})?$",
    r"^aguardando numero$",
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


def _negado(frase: str, inicio: int) -> bool:
    """True se há um 'não' logo antes do trecho casado (ex.: 'não trouxe autorização nova')."""
    return bool(_NEGACAO.search(frase[max(0, inicio - 40):inicio]))


def _frases(texto: str) -> list[str]:
    return [f.strip(" ,") for f in re.split(r"[.;]", texto) if f.strip(" ,")]


def interpretar_observacao(texto: str | None) -> list[Motivo]:
    if not texto or not texto.strip():
        return []
    original = texto.strip()
    motivos: list[Motivo] = []
    vistos: set[str] = set()
    sobrou: list[str] = []

    for frase in _frases(_sem_acento(original)):
        if any(re.search(p, frase) for p in BENIGNAS) or any(re.search(p, frase) for p in COMPLEMENTOS):
            continue
        casou = False
        for codigo, regex, gravidade, mensagem, correcao, encaminhamento in PADROES:
            m = re.search(regex, frase)
            if m and not _negado(frase, m.start()):
                casou = True
                if codigo not in vistos:
                    vistos.add(codigo)
                    motivos.append(Motivo(codigo, gravidade, mensagem, campo="observacao_recepcao",
                                          valor=original, correcao=correcao, encaminhamento=encaminhamento))
        if not casou:
            sobrou.append(frase)

    if sobrou:
        motivos.append(Motivo("OBSERVACAO_NAO_INTERPRETADA", "corrigir",
                              "A recepção escreveu algo que o sistema não sabe interpretar; alguém precisa ler: "
                              + "; ".join(f'"{f}"' for f in sobrou),
                              campo="observacao_recepcao", valor=original,
                              correcao="Ler a observação e decidir manualmente"))
    return motivos
