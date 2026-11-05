"""Helpers de interação com telas JSF/PrimeFaces."""
from __future__ import annotations
from playwright.sync_api import Frame, Page, TimeoutError as PlaywrightTimeout

from .conexao import garantir_logado


def esperar_pronto(page: Page, timeout: int = 30_000) -> None:
    """Espera a página assentar. Requisição pendurada não aborta (quem chama espera o elemento
    certo); se a sessão caiu na tela de login, para com SessaoExpirada."""
    page.wait_for_load_state("load", timeout=timeout)
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout, 10_000))
    except PlaywrightTimeout:
        pass
    garantir_logado(page)
    try:   # máscara de carregamento do PrimeFaces
        page.locator(".ui-blockui:not([hidden])").first.wait_for(state="hidden", timeout=10_000)
    except Exception:
        pass


def clicar_e_navegar(page: Page, seletor: str, timeout: int = 30_000) -> None:
    """Clique que submete um form (post -> redirect -> get): espera a navegação terminar."""
    with page.expect_navigation(wait_until="load", timeout=timeout):
        page.locator(seletor).first.click()
    esperar_pronto(page)


def escolher_opcao(alvo: Page | Frame, seletor_input: str, texto: str) -> None:
    """Escolhe uma opção de selectOneMenu COMO USUÁRIO: abre o widget e clica no item.

    Mudar só o <select> oculto deixa o widget dessincronizado e o JSF não registra a escolha
    ('[Tipo de Documento] obrigatório!', botão 'Gerar' desabilitado). Aceita Frame (modais em iframe)."""
    teclado = (alvo.page if isinstance(alvo, Frame) else alvo).keyboard
    alvo.wait_for_load_state("load")   # o widget só funciona depois que o script da tela o inicializa
    wid = alvo.eval_on_selector(seletor_input, "el => el.id.replace(/_input$/, '')")
    item = alvo.locator(f'[id="{wid}_panel"] li[data-label="{texto}"]').first

    def marcado() -> str:
        return alvo.eval_on_selector(f'[id="{wid}_input"]', "el => el.options[el.selectedIndex]?.text.trim()")

    for _ in range(3):   # o painel às vezes não abre (ou o clique se perde) na 1ª tentativa
        alvo.locator(f'[id="{wid}"]').click()
        try:
            item.click(timeout=3_000)
        except Exception:
            teclado.press("Escape")
        alvo.wait_for_timeout(150)
        if marcado() == texto:
            return
    # plano B: API do widget (dispara o mesmo evento de mudança que o clique)
    ok = alvo.evaluate(
        """([wid, t]) => {
             const w = Object.values(PrimeFaces.widgets).find(w => w && w.id === wid);
             const o = [...document.getElementById(wid + '_input').options].find(o => o.text.trim() === t);
             if (!w || !o) return false; w.selectValue(o.value); return true; }""", [wid, texto])
    if not ok:
        raise LookupError(f"Opção '{texto}' não encontrada em {wid}.")
    if marcado() != texto:
        raise LookupError(f"A opção '{texto}' não ficou selecionada em {wid} (está '{marcado()}').")


def rotulo_da_opcao(alvo: Page | Frame, seletor_input: str, valor: str) -> str | None:
    return alvo.eval_on_selector(
        seletor_input,
        "(el, v) => { const o = [...el.options].find(o => o.value === v); return o ? o.text.trim() : null; }", valor)


def indice_da_linha(page: Page, seletor_body: str, *textos: str) -> int:
    """Índice (0-based, o N dos ids `:N:`) da 1ª <tr> que contém TODOS os textos; -1 se não achar."""
    return page.eval_on_selector(
        seletor_body,
        """(body, ts) => {
             const rows = [...body.querySelectorAll(':scope > tr')];
             for (let i = 0; i < rows.length; i++)
               if (ts.every(t => rows[i].innerText.includes(t))) return i;
             return -1; }""",
        [t for t in textos if t])


def frame_por_url(page: Page, trecho: str, timeout_ms: int = 10_000) -> Frame | None:
    """Os modais do eLaw são IFRAMEs: acha o frame cujo URL contém `trecho`."""
    for _ in range(max(1, timeout_ms // 250)):
        for f in page.frames:
            if trecho in (f.url or ""):
                try:
                    f.wait_for_load_state("load", timeout=5_000)
                except Exception:
                    pass
                return f
        page.wait_for_timeout(250)
    return None
