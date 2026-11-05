"""Cliente do CPJ: contra o mock (TestClient) e contra uma sessão falsa para os casos de falha."""
import json

import pytest
from fastapi.testclient import TestClient

from elaw.cpj import ClienteCPJ, CPJIndisponivel, carregar_credenciais


def _cenario(app, cod):
    e = app.state.estado
    return next(p for p in e.processos.values() if p["cenario"] == cod)


def test_localiza_so_no_grupo_de_trabalho_do_cliente(app_mock, cliente_cpj):
    p = _cenario(app_mock, "contestacao_dois_clientes")
    cadastros = [c for c in app_mock.state.estado.cpj_processos if c["numero_processo"] == p["numero"]]
    assert len(cadastros) == 2 and cadastros[0]["grupo_trabalho"] == 800   # o do OUTRO cliente vem primeiro
    assert cliente_cpj.localizar(p["numero"]) == next(c["pj"] for c in cadastros if c["grupo_trabalho"] == 700)


def test_sem_filtro_de_grupo_pegaria_o_cadastro_errado(app_mock):
    cli = ClienteCPJ("http://testserver/cpj", "robo.leitura", "cpj-demo-123", sessao=TestClient(app_mock),
                     pausa=lambda s: None)
    p = _cenario(app_mock, "contestacao_dois_clientes")
    pj = cli.localizar(p["numero"])
    assert next(c for c in app_mock.state.estado.cpj_processos if c["pj"] == pj)["grupo_trabalho"] == 800


def test_nao_achado_e_none(cliente_cpj):
    assert cliente_cpj.localizar("0000000-00.0000.0.00.0000") is None


def test_paginacao_junta_todas_as_paginas(app_mock):
    cli = ClienteCPJ("http://testserver/cpj", "robo.leitura", "cpj-demo-123", sessao=TestClient(app_mock),
                     pausa=lambda s: None, por_pagina=3)
    assert len(cli.listar("/processos")) == len(app_mock.state.estado.cpj_processos)


def test_404_vira_lista_vazia(cliente_cpj):
    assert cliente_cpj.tramitacoes(999_999_999) == []


def test_relogin_quando_o_token_vence_e_retry_no_503():
    from mock.app import criar_app
    app = criar_app(instavel=True, limite_token=4)       # 503 a cada 13 req. + token vence a cada 4 usos
    cli = ClienteCPJ("http://testserver/cpj", "robo.leitura", "cpj-demo-123", grupo_trabalho=700,
                     sessao=TestClient(app), pausa=lambda s: None)
    total = len([p for p in app.state.estado.cpj_processos if p["grupo_trabalho"] == 700])
    achados = [cli.localizar(p["numero_processo"]) for p in app.state.estado.cpj_processos
               if p["grupo_trabalho"] == 700]
    assert len(achados) == total and all(achados)          # nenhum erro virou "não achado"


def test_baixa_pdf(cliente_cpj, app_mock, tmp_path):
    id_ged = next(d["id_ged"] for d in app_mock.state.estado.cpj_docs.values() if d["nome"].endswith(".pdf"))
    arq = cliente_cpj.baixar(id_ged, tmp_path / "x.pdf")
    assert arq.read_bytes().startswith(b"%PDF-1.4") and arq.read_bytes().rstrip().endswith(b"%%EOF")


# ------------------------------------------------------------------ sessão falsa
class Resp:
    def __init__(self, status, corpo=None, headers=None):
        self.status_code, self._corpo, self.headers = status, corpo, headers or {}
        self.content = json.dumps(corpo).encode() if corpo is not None else b""

    def json(self):
        return self._corpo


class SessaoFalsa:
    def __init__(self, respostas_get, respostas_login=None):
        self.headers, self.gets, self.logins = {}, list(respostas_get), list(respostas_login or [Resp(200, {"token": "t"})])
        self.pedidos = []

    def post(self, url, json=None, timeout=None):
        self.pedidos.append(("POST", url))
        return self.logins.pop(0) if len(self.logins) > 1 else self.logins[0]

    def get(self, url, params=None, timeout=None):
        self.pedidos.append(("GET", url))
        return self.gets.pop(0)


def _cli(sessao):
    return ClienteCPJ("http://x/cpj", "u", "s", sessao=sessao, pausa=lambda s: None)


def test_erro_persistente_nunca_vira_nao_encontrado():
    s = SessaoFalsa([Resp(500)] * 5)
    with pytest.raises(CPJIndisponivel):
        _cli(s).localizar("9000000-00.2026.8.26.0001")


def test_429_respeita_retry_after_e_repete():
    pausas = []
    s = SessaoFalsa([Resp(429, headers={"Retry-After": "7"}), Resp(200, {"data": [{"pj": 5}], "total_page": 1})])
    cli = ClienteCPJ("http://x/cpj", "u", "s", sessao=s, pausa=pausas.append)
    assert cli.localizar("9000000-00.2026.8.26.0001") == 5
    assert pausas == [7.0]


def test_401_faz_novo_login():
    s = SessaoFalsa([Resp(401), Resp(200, {"data": [], "total_page": 1})])
    assert _cli(s).localizar("9000000-00.2026.8.26.0001") is None
    assert [c[0] for c in s.pedidos] == ["POST", "GET", "POST", "GET"]


def test_login_recusado_nao_insiste():
    s = SessaoFalsa([], respostas_login=[Resp(401, {"message": "x"})])
    with pytest.raises(CPJIndisponivel, match="recusou o login"):
        _cli(s)
    assert len(s.pedidos) == 1


def test_login_instavel_tenta_de_novo():
    s = SessaoFalsa([], respostas_login=[Resp(503), Resp(503), Resp(200, {"token": "ok"})])
    assert _cli(s).s.headers["Authorization"] == "Bearer ok"


def test_credenciais_do_ambiente_ou_do_env(tmp_path, monkeypatch):
    monkeypatch.delenv("CPJ_LOGIN", raising=False)
    monkeypatch.delenv("CPJ_SENHA", raising=False)
    env = tmp_path / ".env"
    env.write_text("# comentário\nCPJ_LOGIN=a\nCPJ_SENHA=b\n", encoding="utf-8")
    assert carregar_credenciais(env) == ("a", "b")
    monkeypatch.setenv("CPJ_LOGIN", "do-ambiente")
    assert carregar_credenciais(env)[0] == "do-ambiente"
    monkeypatch.delenv("CPJ_LOGIN")
    with pytest.raises(CPJIndisponivel):
        carregar_credenciais(tmp_path / "nao-existe")
