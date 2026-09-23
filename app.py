"""API e página da conferência de guias. Roda na Vercel (FastAPI) e localmente com uvicorn.

    uvicorn app:app --reload        # http://127.0.0.1:8000

Rotas:
    GET  /                       página com as 80 guias, o relatório e o formulário de guia nova
    GET  /api/guias              lote base verificado (query: data_referencia=AAAA-MM-DD)
    GET  /api/relatorio          relatório de terça em JSON   (/api/relatorio.md em Markdown)
    GET  /api/regras             regras; ?convenio=&procedimento= devolve a regra daquele par
    POST /api/verificar          uma guia (JSON com as colunas do CSV) -> decisão + motivos
    POST /api/verificar-lote     CSV em texto (mesmas colunas) -> lista de decisões + relatório do lote
"""

from __future__ import annotations

import logging
import os
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

from vitalis import VERSAO
from vitalis.lote import carregar_guias, ler_csv, verificar_lote
from vitalis.normalizacao import COLUNAS
from vitalis.regras import carregar_regras, verificar_guia
from vitalis.relatorio import montar_relatorio, relatorio_markdown

log = logging.getLogger("vitalis")
RAIZ = Path(__file__).resolve().parent
app = FastAPI(title="Conferência de guias — Clínica Vitalis", version=VERSAO)

REGRAS = carregar_regras()
GUIAS = carregar_guias()


def _data_referencia(texto: str | None) -> date | None:
    """Query/body -> date. Sem valor: usa DATA_REFERENCIA do ambiente, se houver; senão None (= lançamento)."""
    texto = texto or os.environ.get("DATA_REFERENCIA") or ""
    if not texto.strip():
        return None
    try:
        return date.fromisoformat(texto.strip())
    except ValueError:
        raise HTTPException(400, f"data_referencia '{texto}' inválida; use AAAA-MM-DD")


@app.exception_handler(Exception)
async def erro_inesperado(request: Request, exc: Exception):
    log.exception("erro inesperado em %s", request.url.path)
    return JSONResponse(status_code=500, content={"erro": "falha interna ao processar a requisição",
                                                  "detalhe": type(exc).__name__})


@app.get("/", include_in_schema=False)
def pagina():
    return FileResponse(RAIZ / "public" / "index.html")


@app.get("/api/saude")
def saude():
    return {"ok": True, "versao": VERSAO, "guias_no_lote": len(GUIAS), "regras": REGRAS.get("versao")}


@app.get("/api/guias")
def guias(data_referencia: str | None = Query(None, description="AAAA-MM-DD; padrão = data de lançamento de cada guia")):
    dref = _data_referencia(data_referencia)
    resultados = verificar_lote(GUIAS, REGRAS, data_referencia=dref)
    por_id = {g["id_guia"]: g for g in GUIAS}
    return {"total": len(resultados), "data_referencia": dref.isoformat() if dref else "data de lançamento",
            "guias": [{**por_id[r["id_guia"]], "resultado": r} for r in resultados]}


@app.get("/api/relatorio")
def relatorio(data_referencia: str | None = None):
    dref = _data_referencia(data_referencia)
    rel = montar_relatorio(verificar_lote(GUIAS, REGRAS, data_referencia=dref), GUIAS)
    if dref:
        rel["referencia"] = f"conferência na data {dref.isoformat()}"
    return rel


@app.get("/api/relatorio.md", response_class=PlainTextResponse)
def relatorio_md(data_referencia: str | None = None):
    return relatorio_markdown(relatorio(data_referencia))


@app.get("/api/regras")
def regras(convenio: str | None = None, procedimento: str | None = None):
    """Sem parâmetros: as regras completas. Com convenio e/ou procedimento: só o que interessa àquele par."""
    if convenio is None and procedimento is None:
        return {k: v for k, v in REGRAS.items() if not k.startswith("_")}
    resposta: dict[str, Any] = {}
    if convenio is not None:
        c = REGRAS["_convenios"].get(convenio)
        if c is None:
            raise HTTPException(404, f"convênio '{convenio}' não existe; conhecidos: {', '.join(REGRAS['_convenios'])}")
        resposta["convenio"] = c
    if procedimento is not None:
        p = REGRAS["_procedimentos"].get(procedimento)
        if p is None:
            raise HTTPException(404, f"procedimento '{procedimento}' não está na tabela")
        resposta["procedimento"] = p
    if convenio is not None and procedimento is not None:
        resposta["coberto"] = procedimento in resposta["convenio"]["procedimentos_cobertos"]
    return resposta


def _extrair_guia(corpo: Any) -> tuple[dict, str | None]:
    if not isinstance(corpo, dict):
        raise HTTPException(400, "o corpo precisa ser um objeto JSON com as colunas da guia")
    dref = None
    if "guia" in corpo and isinstance(corpo["guia"], dict):
        dref = corpo.get("data_referencia")
        corpo = corpo["guia"]
    desconhecidas = sorted(set(corpo) - set(COLUNAS))
    if desconhecidas:
        raise HTTPException(400, {"erro": "colunas desconhecidas", "colunas": desconhecidas,
                                  "aceitas": COLUNAS})
    if not str(corpo.get("id_guia", "")).strip():
        raise HTTPException(400, "id_guia é obrigatório")
    guia = {c: ("" if corpo.get(c) is None else str(corpo.get(c))) for c in COLUNAS}
    return guia, dref


@app.post("/api/verificar")
async def verificar(request: Request):
    """Corpo: a guia como objeto JSON (colunas do CSV), ou {"guia": {...}, "data_referencia": "AAAA-MM-DD"}.
    A guia é comparada com o lote base para duplicidade. Não é gravada."""
    try:
        corpo = await request.json()
    except Exception:
        raise HTTPException(400, "corpo não é JSON válido")
    guia, dref_texto = _extrair_guia(corpo)
    dref = _data_referencia(dref_texto or request.query_params.get("data_referencia"))
    return verificar_guia(guia, REGRAS, contexto=GUIAS, data_referencia=dref)


@app.post("/api/verificar-lote")
async def verificar_lote_csv(request: Request, data_referencia: str | None = None):
    """Corpo: o CSV em texto (Content-Type text/csv ou text/plain), com o cabeçalho do sistema de gestão."""
    texto = (await request.body()).decode("utf-8-sig", errors="replace")
    if not texto.strip():
        raise HTTPException(400, "corpo vazio; envie o CSV em texto")
    try:
        guias = ler_csv(texto)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if not guias:
        raise HTTPException(400, "o CSV não tem nenhuma linha de guia")
    dref = _data_referencia(data_referencia)
    resultados = verificar_lote(guias, REGRAS, data_referencia=dref)
    return {"total": len(resultados), "resultados": resultados, "relatorio": montar_relatorio(resultados, guias)}
