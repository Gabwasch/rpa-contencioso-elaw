"""
Conexão com o Chrome JÁ AUTENTICADO pelo operador — o robô NUNCA faz login.

Modelo: o operador abre o Chrome com --remote-debugging-port e entra no eLaw passando
pelo SSO/MFA corporativo. O robô se ACOPLA a essa sessão via CDP (connect_over_cdp) e
reaproveita os cookies dela: nunca vê senha nem código de MFA. Ao terminar, só solta a
conexão — a janela do operador continua aberta.

Se a sessão expirar no meio do trabalho, a página cai na tela de login: o robô para com
SessaoExpirada (código de saída 2) em vez de tentar entrar sozinho.
"""
from __future__ import annotations
from dataclasses import dataclass
from urllib.parse import urlparse

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

MARCAS_LOGIN = ("login.elaw", "/sso/", "/saml")

_BASE = "http://127.0.0.1:8701"


class NaoAutenticado(RuntimeError):
    pass


class SessaoExpirada(NaoAutenticado):
    pass


class ChromeNaoEncontrado(RuntimeError):
    pass


def configurar(base_url: str) -> None:
    global _BASE
    _BASE = base_url.rstrip("/")


def url(caminho: str) -> str:
    return f"{_BASE}/{caminho.lstrip('/')}"


def host() -> str:
    return urlparse(_BASE).netloc


@dataclass
class Sessao:
    pw: Playwright
    browser: Browser
    page: Page

    def fechar(self) -> None:
        """Solta o Playwright. NÃO fecha o Chrome do operador (via CDP, close() só desconecta)."""
        for passo in (self.browser.close, self.pw.stop):
            try:
                passo()
            except Exception:
                pass


def esta_logado(page: Page) -> bool:
    u = (page.url or "").lower()
    return host() in u and not any(m in u for m in MARCAS_LOGIN)


def garantir_logado(page: Page) -> None:
    if not esta_logado(page):
        raise SessaoExpirada("A sessão do eLaw expirou (a página caiu na tela de login). Faça o login na "
                             "janela do Chrome e rode o robô de novo.")


def conectar(cdp_url: str, base_url: str | None = None, slow_mo: int = 0) -> Sessao:
    if base_url:
        configurar(base_url)
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.connect_over_cdp(cdp_url, slow_mo=slow_mo or None)
    except Exception as e:
        pw.stop()
        raise ChromeNaoEncontrado(f"Não achei o Chrome em {cdp_url}. Abra o Chrome do robô (porta de depuração) "
                                  f"e faça o login no eLaw primeiro.\n{type(e).__name__}: {e}") from None
    ctx = browser.contexts[0] if browser.contexts else browser.new_context()
    # reaproveita uma aba que já esteja no eLaw; senão abre uma (os cookies da sessão valem para ela)
    # prefere a aba JÁ logada (pode haver outra aba parada na tela de login) e a traz para a frente:
    # numa aba em segundo plano o Chrome pode não entregar os cliques do mouse
    abas = [p for p in ctx.pages if host() in (p.url or "")]
    page = next((p for p in abas if esta_logado(p)), None) or (abas[0] if abas else ctx.new_page())
    page.bring_to_front()
    # sempre recomeça pela home: uma aba aberta desde ontem MOSTRA o eLaw com a sessão já vencida —
    # só navegando se descobre
    page.goto(url("homePage.elaw"), wait_until="load")
    if not esta_logado(page):
        Sessao(pw, browser, page).fechar()
        raise NaoAutenticado("O eLaw não está autenticado nesta sessão do Chrome. Faça o login (SSO/MFA) "
                             "na janela aberta e rode o robô de novo.")
    page.set_default_timeout(20_000)
    return Sessao(pw, browser, page)
