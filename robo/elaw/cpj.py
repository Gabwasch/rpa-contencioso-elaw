"""
Cliente da API REST do CPJ — SOMENTE LEITURA.

Lições que viraram código:
  * o login às vezes não responde (e logo depois responde em <1 s) -> timeout curto + novas tentativas;
    credencial recusada (4xx) não adianta repetir;
  * sob carga a API devolve 401 (token vencido), 429 ou 5xx -> repetir, respeitando Retry-After;
  * NUNCA tratar erro como "processo não existe": só 404/lista vazia é "não achado";
    qualquer outra falha vira CPJIndisponivel (a tarefa fica para a próxima rodada);
  * o mesmo nº de processo pode estar cadastrado para OUTRO cliente do escritório ->
    filtrar pelo grupo de trabalho do cliente.

Credenciais vêm do ambiente/.env (CPJ_LOGIN, CPJ_SENHA) — nunca do código nem do log.
"""
from __future__ import annotations
import os
import time
from pathlib import Path
from typing import Callable

import requests

from . import cnj


class CPJIndisponivel(RuntimeError):
    pass


def carregar_credenciais(arquivo_env: Path | None) -> tuple[str, str]:
    """(login, senha) das variáveis de ambiente ou, na falta, do arquivo .env."""
    env = dict(os.environ)
    if arquivo_env and Path(arquivo_env).exists():
        for linha in Path(arquivo_env).read_text(encoding="utf-8").splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                k, v = linha.split("=", 1)
                env.setdefault(k.strip(), v.strip())
    login, senha = env.get("CPJ_LOGIN"), env.get("CPJ_SENHA")
    if not login or not senha:
        raise CPJIndisponivel("Credenciais do CPJ ausentes: defina CPJ_LOGIN e CPJ_SENHA (ambiente ou .env).")
    return login, senha


class ClienteCPJ:
    def __init__(self, base_url: str, login: str, senha: str, grupo_trabalho: int | None = None,
                 sessao=None, pausa: Callable[[float], None] = time.sleep, por_pagina: int = 200):
        self.base = base_url.rstrip("/") + "/api/v3"
        self._credenciais = (login, senha)
        self.grupo_trabalho = grupo_trabalho or None
        self.s = sessao or requests.Session()     # qualquer objeto "tipo requests" (os testes injetam um falso)
        self.s.headers.update({"Accept": "application/json"})
        self._pausa = pausa
        self.por_pagina = por_pagina
        self.requisicoes = 0
        self._login()

    # ------------------------------------------------------------ transporte
    def _login(self, tentativas: int = 4) -> None:
        ultimo = "sem resposta"
        for n in range(tentativas):
            try:
                r = self.s.post(f"{self.base}/login", timeout=20,
                                json={"login": self._credenciais[0], "password": self._credenciais[1]})
            except (requests.RequestException, OSError) as e:
                ultimo = type(e).__name__
                self._pausa(2 * (n + 1))
                continue
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
                self._pausa(2 * (n + 1))
                continue
            if r.status_code >= 400:   # sem detalhes: a resposta pode ecoar dados da credencial
                raise CPJIndisponivel(f"A API do CPJ recusou o login (HTTP {r.status_code}). Confira as credenciais.")
            self.s.headers["Authorization"] = "Bearer " + r.json()["token"]
            return
        raise CPJIndisponivel(f"Não consegui entrar na API do CPJ ({ultimo}, {tentativas} tentativas).")

    def _get(self, caminho: str, params: dict | None = None, tentativas: int = 5):
        ultimo = "sem resposta"
        for n in range(tentativas):
            self.requisicoes += 1
            try:
                r = self.s.get(f"{self.base}{caminho}", params=params, timeout=60)
            except (requests.RequestException, OSError) as e:
                ultimo = type(e).__name__
                self._pausa(2 * (n + 1))
                continue
            if r.status_code == 401:          # token vencido: entra de novo e repete
                ultimo = "HTTP 401"
                self._login()
                continue
            if r.status_code == 429 or r.status_code >= 500:
                ultimo = f"HTTP {r.status_code}"
                espera = r.headers.get("Retry-After")
                self._pausa(float(espera) if espera and espera.replace(".", "", 1).isdigit() else 2 * (n + 1))
                continue
            return r
        raise CPJIndisponivel(f"A API do CPJ não respondeu ({caminho}; {ultimo}; {tentativas} tentativas).")

    def listar(self, caminho: str, params: dict | None = None) -> list[dict]:
        """GET paginado (envelope data/total_page). 404/204 -> lista vazia; outro erro -> CPJIndisponivel."""
        params = {**(params or {}), "per_page": self.por_pagina, "current_page": 1}
        itens: list[dict] = []
        while True:
            r = self._get(caminho, params)
            if r.status_code in (204, 404) or not r.content:
                return itens
            if r.status_code >= 400:
                raise CPJIndisponivel(f"A API do CPJ recusou a consulta ({caminho}; HTTP {r.status_code}).")
            corpo = r.json()
            if not (isinstance(corpo, dict) and "data" in corpo):
                return corpo if isinstance(corpo, list) else [corpo]
            itens += [i for i in corpo["data"] or [] if isinstance(i, dict)]
            if params["current_page"] >= (corpo.get("total_page") or 1):
                return itens
            params["current_page"] += 1

    def baixar(self, id_ged: int | str, destino: Path) -> Path:
        r = self._get(f"/documentos/{id_ged}")
        if r.status_code >= 400:
            raise CPJIndisponivel(f"Não consegui baixar o documento {id_ged} do CPJ (HTTP {r.status_code}).")
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(r.content)
        return destino

    # ------------------------------------------------------------ consultas do robô
    def localizar(self, numero: str) -> int | None:
        """PJ (id do cadastro) do processo principal no grupo de trabalho do cliente; None se não existe."""
        filtro = {"filter[numero_processo_pesq][_eq]": cnj.so_digitos(numero)}
        if self.grupo_trabalho:
            filtro["filter[grupo_trabalho][_eq]"] = str(self.grupo_trabalho)
        achados = [p for p in self.listar("/processos", filtro) if p.get("pj")]
        if not achados:
            return None
        achados.sort(key=lambda p: p.get("incidente") or 0)   # incidente 0 = processo principal
        return achados[0]["pj"]

    def tramitacoes(self, pj: int) -> list[dict]:
        return self.listar(f"/processos/{pj}/tramitacoes")

    def documentos(self, pj: int) -> list[dict]:
        return self.listar(f"/processos/{pj}/documentos")

    def documentos_da_tarefa(self, id_tramitacao: int) -> list[dict]:
        return self.listar(f"/tarefas/{id_tramitacao}/documentos")
