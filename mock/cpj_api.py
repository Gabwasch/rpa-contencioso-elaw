"""
API REST "parecida com a do CPJ" (somente leitura), em /cpj/api/v3.

Imita o que importa para o robô:
  - POST /login -> token Bearer (o token "vence" depois de N usos -> 401 -> o cliente re-loga);
  - GET paginado com envelope {data, current_page, per_page, total, total_page};
  - filtros no formato filter[campo][_eq]=valor;
  - instabilidade: com `instavel`, 1 a cada 13 requisições responde 503 + Retry-After
    (o cliente precisa repetir — e NUNCA tratar o erro como "processo não existe").
"""
from __future__ import annotations
import math
import re
import secrets

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from .estado import Estado
from .pdf import gerar_pdf


def criar_router(estado: Estado) -> APIRouter:
    r = APIRouter(prefix="/cpj/api/v3")

    def erro(status: int, msg: str, **headers) -> JSONResponse:
        return JSONResponse({"message": msg}, status_code=status, headers=headers or None)

    def autorizar(request: Request) -> JSONResponse | None:
        with estado.lock:
            estado.cpj_contador += 1
            n = estado.cpj_contador
        if estado.instavel and n % 13 == 0:
            return erro(503, "Serviço temporariamente indisponível", **{"Retry-After": "0"})
        token = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        if token not in estado.cpj_tokens:
            return erro(401, "Token inválido ou expirado")
        estado.cpj_tokens[token] += 1
        if estado.cpj_tokens[token] > estado.limite_token:
            del estado.cpj_tokens[token]
            return erro(401, "Token expirado")
        return None

    def paginar(request: Request, itens: list[dict]) -> JSONResponse:
        try:
            por_pagina = max(1, min(500, int(request.query_params.get("per_page", 50))))
            pagina = max(1, int(request.query_params.get("current_page", 1)))
        except ValueError:
            return erro(400, "Parâmetros de paginação inválidos")
        total_paginas = max(1, math.ceil(len(itens) / por_pagina))
        fatia = itens[(pagina - 1) * por_pagina: pagina * por_pagina]
        return JSONResponse({"data": fatia, "current_page": pagina, "per_page": por_pagina,
                             "total": len(itens), "total_page": total_paginas})

    def doc_json(d: dict) -> dict:
        # como no sistema real, o `path` às vezes vem com o caminho de rede inteiro
        caminho = (f"N:\\Contencioso\\Cliente Exemplo\\{d['pj']}\\{d['nome']}" if d["id_ged"] % 2
                   else d["nome"])
        return {"id_ged": d["id_ged"], "pj": d["pj"], "path": caminho, "data_criacao": d["data_criacao"],
                "id_tramitacao": d["id_tramitacao"], "tipo_documento": None}

    def proc_existe(pj: int) -> bool:
        return any(p["pj"] == pj for p in estado.cpj_processos)

    @r.post("/login")
    async def login(request: Request):
        try:
            corpo = await request.json()
        except Exception:
            return erro(400, "JSON inválido")
        if corpo.get("login") != estado.cpj_cred["login"] or corpo.get("password") != estado.cpj_cred["senha"]:
            return erro(401, "Credenciais inválidas")
        token = secrets.token_urlsafe(24)
        estado.cpj_tokens[token] = 0
        return {"token": token, "token_type": "Bearer"}

    @r.get("/processos")
    async def processos(request: Request):
        if (falha := autorizar(request)) is not None:
            return falha
        q = request.query_params
        itens = list(estado.cpj_processos)
        if (num := q.get("filter[numero_processo_pesq][_eq]")) is not None:
            itens = [p for p in itens if re.sub(r"\D", "", p["numero_processo"]) == re.sub(r"\D", "", num)]
        if (gt := q.get("filter[grupo_trabalho][_eq]")) is not None:
            itens = [p for p in itens if str(p["grupo_trabalho"]) == gt]
        return paginar(request, itens)

    @r.get("/processos/{pj}/tramitacoes")
    async def tramitacoes(pj: int, request: Request):
        if (falha := autorizar(request)) is not None:
            return falha
        if not proc_existe(pj):
            return erro(404, "Processo não encontrado")
        itens = [{"id_tramitacao": t["id_tramitacao"], "pj": pj,
                  "evento_desc": {"label": t["evento"]}, "situacao_desc": {"label": t["situacao"]},
                  "data_hora_lan": t["data_hora_lan"], "texto": t["texto"]}
                 for t in estado.cpj_tram if t["pj"] == pj]
        return paginar(request, itens)

    @r.get("/processos/{pj}/documentos")
    async def documentos(pj: int, request: Request):
        if (falha := autorizar(request)) is not None:
            return falha
        if not proc_existe(pj):
            return erro(404, "Processo não encontrado")
        return paginar(request, [doc_json(d) for d in estado.cpj_docs.values() if d["pj"] == pj])

    @r.get("/tarefas/{id_tramitacao}/documentos")
    async def documentos_da_tarefa(id_tramitacao: int, request: Request):
        if (falha := autorizar(request)) is not None:
            return falha
        return paginar(request, [doc_json(d) for d in estado.cpj_docs.values()
                                 if d["id_tramitacao"] == id_tramitacao])

    @r.get("/documentos/{id_ged}")
    async def baixar(id_ged: int, request: Request):
        if (falha := autorizar(request)) is not None:
            return falha
        d = estado.cpj_docs.get(id_ged)
        if d is None:
            return erro(404, "Documento não encontrado")
        proc = next(p for p in estado.cpj_processos if p["pj"] == d["pj"])
        if d["nome"].lower().endswith(".pdf"):
            corpo = gerar_pdf([f"Arquivo: {d['nome']}", f"Processo: {proc['numero_processo']}",
                               f"Cadastro no CPJ (PJ): {d['pj']}", f"ID do documento: {id_ged}",
                               "", "Conteúdo meramente ilustrativo."], titulo=d["nome"].rsplit(".", 1)[0])
            return Response(corpo, media_type="application/pdf")
        return Response(b"arquivo ficticio", media_type="application/octet-stream")

    return r
