# Conferência de guias de convênio — Clínica Vitalis

Solução da etapa técnica do processo seletivo da Expert Integrado (Consultor de Negócios com IA).
Confere as guias de convênio **antes** de irem ao convênio, aplica as regras dos três convênios às 80 guias
de agosto, aceita guia nova por API/formulário/CSV e gera o relatório de terça do Dr. Renato.

- **Solução no ar:** _(URL publicada após o deploy na Vercel)_
- **Repositório:** https://github.com/rafaelbertti/vitalis-guias
- **Relatório de terça:** [`relatorio/relatorio_terca.md`](relatorio/relatorio_terca.md) (gerado por `python -m vitalis.relatorio`; também em `GET /api/relatorio.md`)

## Como funciona em uma frase

Um **motor de regras determinístico em Python** (`vitalis/regras.py`), sem IA na decisão, é a única fonte de
verdade: a API, a página, o relatório, o MCP e a Skill chamam a mesma função `verificar_guia`.

```
guia (colunas do CSV) ──► normalização ──► 10 regras ──► decisão + motivos + o que corrigir
                          (datas, valor)   (uma função curta cada)
```

Decisões possíveis:

| Decisão | Significa | Exemplos |
|---|---|---|
| `ok` | pode enviar ao convênio | — |
| `corrigir` | a recepção resolve antes do envio | campo obrigatório vazio, número de autorização a lançar, possível duplicidade, observação que ninguém interpretou |
| `nao_enviar` | nas condições atuais o convênio não aceita, ou o caminho é outro | autorização vencida, sessão acima do limite, procedimento não coberto, paciente pediu particular |

Cada motivo tem um **código estável** (`AUTORIZACAO_VENCIDA`, `SESSAO_ACIMA_LIMITE`, `CAMPO_OBRIGATORIO_VAZIO`…),
a gravidade (`bloqueia` / `corrigir` / `aviso` / `info`), o campo, o valor observado, a regra aplicada e o que corrigir.
`encaminhamento` diz se a guia segue no `convenio` ou vai para `particular`.

## Como uma guia nova entra e a decisão sai

Três caminhos, todos no mesmo motor:

1. **API** — `POST /api/verificar` com a guia em JSON, nas mesmas colunas do `guias.csv`. É o caminho para o
   sistema de gestão chamar no lançamento (ou antes do envio) sem ninguém precisar lembrar.
2. **Formulário** na página (seção "Guia nova"), que chama a mesma rota.
3. **Lote em CSV** — `POST /api/verificar-lote` com a exportação do sistema de gestão (ou upload na página).

Além disso, o MCP e a Skill (ver abaixo) usam a mesma função.

### Contrato da API

```bash
curl -X POST https://<url-da-solucao>/api/verificar \
  -H "Content-Type: application/json" \
  -d '{
    "id_guia": "G-2609-0001", "unidade": "Centro", "data_atendimento": "2026-09-22", "paciente": "P-1099",
    "convenio": "Vitalcard", "carteirinha": "555000111", "cid": "M54.5",
    "procedimento_codigo": "50000470", "procedimento_descricao": "Sessão de fisioterapia musculoesquelética",
    "numero_autorizacao": "AUT999001", "autorizacao_validade": "2026-09-30",
    "autorizacao_sessoes_limite": "10", "sessao_numero_na_autorizacao": "11",
    "profissional": "Camila Torres", "profissional_registro": "CREFITO-3 176590-F",
    "valor": "62,00", "observacao_recepcao": "", "data_lancamento": "2026-09-22"
  }'
```

Resposta (`200`):

```json
{
  "id_guia": "G-2609-0001",
  "decisao": "nao_enviar",
  "encaminhamento": "convenio",
  "motivos": [
    {"codigo": "SESSAO_ACIMA_LIMITE", "gravidade": "bloqueia",
     "mensagem": "Sessão 11 de uma autorização que cobre no máximo 10 (Vitalcard)",
     "campo": "sessao_numero_na_autorizacao", "valor": "11", "regra": "limite_sessoes_por_autorizacao",
     "correcao": "Conferir a contagem de sessões; acima do limite é preciso nova autorização"},
    {"codigo": "VALOR_NORMALIZADO", "gravidade": "aviso", "mensagem": "valor estava como '62,00' e foi lido como 62.00", "...": "..."}
  ],
  "corrigir": ["Conferir a contagem de sessões; acima do limite é preciso nova autorização"],
  "valor": "62.00",
  "data_referencia": "2026-09-22",
  "versao_regras": "agosto/2026 / motor 2026-09-23.1"
}
```

Regras do contrato:

- Colunas faltantes são tratadas como vazias e viram pendência de negócio na resposta (`200`, `decisao: corrigir`).
  Só `id_guia` é obrigatório no envelope.
- Coluna desconhecida, JSON inválido, `id_guia` vazio ou `data_referencia` inválida → `400` com a explicação.
  Erro inesperado → `500` com `{"erro": ...}` sem stack trace.
- `data_referencia` (opcional, query ou envelope `{"guia": {...}, "data_referencia": "AAAA-MM-DD"}`) é o dia em
  que a conferência acontece. Padrão: a **data de lançamento** da guia, que é como a clínica confere o lote
  (esclarecimento do avaliador). Para simular "e se eu enviar hoje?", passe a data de hoje: o prazo de envio
  é reavaliado e, vencido, bloqueia.
- A guia nova é comparada com o lote de agosto para **possível duplicidade** e **não é gravada** (ver "O que ficou de fora").

Outras rotas: `GET /api/guias` (as 80 verificadas), `GET /api/relatorio` e `/api/relatorio.md`,
`GET /api/regras?convenio=Plano%20Bem&procedimento=20103301`, `GET /api/saude`, `GET /docs` (OpenAPI).

## Rodar localmente

```bash
python -m venv .venv && .venv/Scripts/activate   # Linux/mac: source .venv/bin/activate
pip install -r requirements.txt pytest httpx
uvicorn app:app --reload                          # http://127.0.0.1:8000
python -m pytest -q                               # 143 testes
python -m vitalis.relatorio                       # gera relatorio/relatorio_terca.md e .json
```

Variáveis de ambiente (todas opcionais, ver `.env.example`): `GUIAS_CSV`, `REGRAS_JSON`, `DATA_REFERENCIA`.
Não há chave nem senha: a solução não usa serviço externo.

## Estrutura

```
app.py                    API FastAPI + página (Vercel usa este arquivo)
public/index.html         página: relatório, tabela das 80 guias, formulário de guia nova, upload de CSV
vitalis/regras.py         o motor: REGRAS = [uma função por regra], verificar_guia(), decidir()
vitalis/normalizacao.py   datas (AAAA-MM-DD e dd/mm/aaaa), valores ("62,00"), inteiros; Motivo
vitalis/texto_livre.py    padrões da observação da recepção (benignas, 5 casos de ação, resto -> revisão)
vitalis/lote.py           ler CSV, verificar lote com contexto (duplicidade)
vitalis/relatorio.py      relatório de terça (JSON + Markdown)
vitalis/dados/            guias.csv e regras_convenio.json (materiais da prova)
tests/                    143 testes; tests/esperado_80.csv é o oráculo das 80 guias, escrito à mão
relatorio/                relatório gerado
```

## Para mudar uma regra

Abra `vitalis/regras.py`. Cada regra é uma função `regra_x(g, ctx) -> list[Motivo]` e todas estão na lista
`REGRAS`. Para exigir CID também no Saúde Interior, por exemplo, basta editar `regras_convenio.json`; para
uma regra nova (ex.: "consulta só com médico CRM"), escreva a função e acrescente à lista. Rode `pytest`:
o oráculo das 80 guias avisa o que mudou.

## MCP e Skill

_(em construção — próxima etapa)_

## Como fiz

_(em construção — será preenchido antes da entrega)_
