"""Conferência de guias de convênio da Clínica Vitalis.

Um motor de regras determinístico (``vitalis.regras``) usado por três portas:
a API/página (``app.py``), o MCP (``mcp_server``) e o relatório de terça
(``python -m vitalis.relatorio``). A decisão nunca diverge porque é a mesma função.
"""

VERSAO = "0.1.0"
