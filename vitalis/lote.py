"""Carregar o CSV de guias e verificar um lote inteiro com contexto (duplicidade)."""

from __future__ import annotations

import csv
import io
import os
from datetime import date
from pathlib import Path

from .normalizacao import COLUNAS
from .regras import verificar_guia

_AQUI = Path(__file__).resolve().parent
CAMINHO_GUIAS_PADRAO = _AQUI / "dados" / "guias.csv"


def ler_csv(texto: str) -> list[dict]:
    """Lê um CSV (texto) com o cabeçalho do sistema de gestão. Colunas faltantes viram vazio."""
    leitor = csv.DictReader(io.StringIO(texto))
    if leitor.fieldnames is None:
        raise ValueError("CSV vazio")
    faltando = [c for c in ("id_guia", "convenio", "procedimento_codigo") if c not in leitor.fieldnames]
    if faltando:
        raise ValueError(f"CSV sem as colunas obrigatórias: {', '.join(faltando)}")
    guias = []
    for linha in leitor:
        if not any((v or "").strip() for v in linha.values()):
            continue
        guias.append({c: (linha.get(c) or "").strip() for c in COLUNAS})
    return guias


def carregar_guias(caminho: str | os.PathLike | None = None) -> list[dict]:
    caminho = Path(caminho or os.environ.get("GUIAS_CSV") or CAMINHO_GUIAS_PADRAO)
    with open(caminho, encoding="utf-8") as f:
        return ler_csv(f.read())


def verificar_lote(guias: list[dict], regras: dict, data_referencia: date | None = None) -> list[dict]:
    """Verifica cada guia com as demais como contexto. ``data_referencia=None`` = data de lançamento de cada uma."""
    return [verificar_guia(g, regras, contexto=guias, data_referencia=data_referencia) for g in guias]
