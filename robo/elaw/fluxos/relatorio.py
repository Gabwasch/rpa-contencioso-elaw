"""
Relatórios do eLaw: modal "Gerar Relatório" (IFRAME) + entrega assíncrona em "Meus Relatórios".

Armadilhas que este módulo resolve:
  * a geração é ASSÍNCRONA: o modal só devolve o ID da solicitação; o arquivo aparece minutos
    depois em "Meus Relatórios" -> polling;
  * "Meus Relatórios" já tem relatórios ANTIGOS -> baixar só a linha com o ID da NOSSA solicitação
    (ou, sem ele, um ID que não existia antes de gerar), nunca "o primeiro processado da lista";
  * a lista abre VAZIA e guarda o filtro de data da sessão (de ontem, numa aba aberta desde ontem)
    -> sempre "Limpar Pesquisa" + "Pesquisar";
  * o modelo precisa ser escolhido com clique real, senão "Gerar" fica desabilitado;
  * com connect_over_cdp o `expect_download` não dispara -> Page.setDownloadBehavior apontando
    para uma pasta + varredura da pasta pelo arquivo novo (ignorando .crdownload).
"""
from __future__ import annotations
import os
import re
import time
from pathlib import Path

from playwright.sync_api import Page

from .. import seletores as S
from ..conexao import garantir_logado, url
from ..util import clicar_e_navegar, escolher_opcao, esperar_pronto, frame_por_url, rotulo_da_opcao


class RelatorioIndisponivel(RuntimeError):
    pass


_LINHAS_JS = r"""() => [...document.querySelectorAll('tbody[id$="_data"] > tr')].map(tr => {
  const td = [...tr.querySelectorAll(':scope > td')].map(c => c.innerText.trim());
  const id = td.find(t => /^\d+$/.test(t));
  return {id: id || null, processado: !!tr.querySelector('img[title="Processado"]'),
          clipe: !!tr.querySelector('a img[src*="clip.png"]')};
}).filter(r => r.id)"""
EXTENSOES = (".xlsx", ".xls", ".csv")
_RE_ID_SOLICITACAO = re.compile(r"\bID\s+(\d+)")


# ---------------------------------------------------------------- "Meus Relatórios"
def abrir_meus_relatorios(page: Page) -> None:
    """Só se chega pela maleta (o link tem um token da sessão; URL direta = Acesso Negado)."""
    if S.MEUS_REL_URL_HINT in (page.url or ""):
        return
    if page.locator(".ui-dialog-mask").count():   # modal aberto bloquearia a maleta
        page.goto(url("homePage.elaw"), wait_until="domcontentloaded")
    link = page.locator(S.MEUS_REL_LINK, has_text="Meus Relat").first
    for _ in range(2):   # a maleta é liga/desliga: se o painel já estava aberto, o 1º clique fecha
        page.locator(S.MENU_MALETA).first.click()
        try:
            link.wait_for(state="visible", timeout=3_000)
            break
        except Exception:
            pass
    with page.expect_navigation(wait_until="load"):
        link.click()
    esperar_pronto(page)


def atualizar_meus_relatorios(page: Page) -> list[dict]:
    """Limpar (o filtro de data da sessão pode ser de ontem) + Pesquisar (a lista abre vazia)."""
    try:
        abrir_meus_relatorios(page)
        clicar_e_navegar(page, S.MEUS_REL_BTN_LIMPAR)
        clicar_e_navegar(page, S.MEUS_REL_BTN_PESQUISAR)
    except Exception:
        garantir_logado(page)   # se foi a sessão que caiu, sai com SessaoExpirada (mensagem clara)
        raise
    return page.evaluate(_LINHAS_JS)


def ids_existentes(page: Page) -> set[str]:
    """Retrato dos IDs já presentes em 'Meus Relatórios' (antes de gerar)."""
    return {r["id"] for r in atualizar_meus_relatorios(page)}


# ---------------------------------------------------------------- modal "Gerar Relatório"
def gerar_no_modal(page: Page, template: str, btn_excel: str) -> str | None:
    """Com a pesquisa já feita: Excel -> Modelos Pré-Configurado -> modelo -> Gerar.
    Devolve o ID da solicitação mostrado na confirmação (ou None se não conseguir ler)."""
    page.locator(btn_excel).first.click()
    fr = frame_por_url(page, S.REL_IFRAME_HINT)
    if fr is None:
        raise RelatorioIndisponivel("O modal 'Gerar Relatório' não abriu depois do clique em Excel.")
    fr.get_by_text(S.REL_OPCAO_PRECONFIG, exact=False).first.click()
    with fr.expect_navigation(wait_until="load"):
        fr.locator(S.REL_BTN_CONTINUAR).click()
    fr = frame_por_url(page, S.REL_IFRAME_HINT) or fr
    fr.wait_for_selector(S.REL_TEMPLATE_INPUT, state="attached", timeout=15_000)
    rotulo = rotulo_da_opcao(fr, S.REL_TEMPLATE_INPUT, template)
    if rotulo is None:
        raise RelatorioIndisponivel(f"O modelo {template} não existe na lista do eLaw.")
    escolher_opcao(fr, S.REL_TEMPLATE_INPUT, rotulo)   # clique real: só assim o "Gerar" habilita
    try:
        fr.wait_for_selector(f"{S.REL_BTN_GERAR}:not([disabled])", timeout=10_000)
    except Exception:
        raise RelatorioIndisponivel("O eLaw deixou o botão 'Gerar Relatório' desabilitado. Tente mais tarde.") from None
    with fr.expect_navigation(wait_until="load"):
        fr.locator(S.REL_BTN_GERAR).click()
    fr = frame_por_url(page, S.REL_IFRAME_HINT) or fr
    m = _RE_ID_SOLICITACAO.search(fr.evaluate("() => document.body.innerText"))
    try:
        fr.locator(S.REL_BTN_FECHAR_FINAL).click(timeout=5_000)
    except Exception:
        pass
    return m.group(1) if m else None


# ---------------------------------------------------------------- download
def _forcar_pasta_de_download(page: Page, pasta: Path) -> None:
    """connect_over_cdp: o evento de download do Playwright não chega -> manda o Chrome salvar direto
    na pasta. (Page.setDownloadBehavior é o que funciona por aba; Browser.* é o plano B.)"""
    try:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Page.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(pasta)})
    except Exception:
        cdp = page.context.browser.new_browser_cdp_session()
        cdp.send("Browser.setDownloadBehavior", {"behavior": "allow", "downloadPath": str(pasta)})


def baixar_novo(page: Page, pasta: Path, ids_antes: set[str], id_alvo: str | None,
                timeout_s: int = 180, intervalo_s: float = 2.0) -> dict:
    """Espera a solicitação `id_alvo` (ou um ID novo) ficar 'Processado' e baixa o arquivo."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    _forcar_pasta_de_download(page, pasta)
    antes = set(os.listdir(pasta))
    fim = time.monotonic() + timeout_s
    while time.monotonic() < fim:
        linhas = atualizar_meus_relatorios(page)
        candidatos = [r for r in linhas if (r["id"] == id_alvo if id_alvo else r["id"] not in ids_antes)]
        prontos = [r for r in candidatos if r["processado"] and r["clipe"]]
        if not prontos:
            page.wait_for_timeout(int(intervalo_s * 1000))   # ainda "Executando"
            continue
        rid = max(prontos, key=lambda r: int(r["id"]))["id"]
        linha = page.locator('tbody[id$="_data"] > tr', has=page.locator(f'td:text-is("{rid}")'))
        linha.locator(S.MEUS_REL_CLIPE).first.click()
        for _ in range(60):   # espera o arquivo aparecer inteiro na pasta
            time.sleep(0.5)
            # só planilhas: com o download redirecionado, o Chrome pode largar outros arquivos na mesma
            # pasta (atualização de componentes num perfil novo, visto na demo) — e .crdownload é parcial
            novos = sorted((f for f in set(os.listdir(pasta)) - antes if f.lower().endswith(EXTENSOES)),
                           key=lambda f: rid not in f)   # o que traz o ID da solicitação no nome primeiro
            if novos:
                arq = pasta / novos[0]
                return {"ok": True, "arquivo": str(arq), "bytes": arq.stat().st_size, "id_relatorio": rid}
        return {"ok": False, "motivo": "cliquei no download, mas o arquivo não chegou na pasta"}
    return {"ok": False, "motivo": f"o relatório não ficou pronto em {timeout_s} s"}


def renomear(resultado: dict, prefixo: str) -> dict:
    """Troca o nome do eLaw (report_elawReport_99_<id+lixo>.xlsx) por um legível, mantendo o ID."""
    if not resultado.get("ok") or not resultado.get("arquivo"):
        return resultado
    origem = Path(resultado["arquivo"])
    sufixo = f"_{resultado['id_relatorio']}" if resultado.get("id_relatorio") else ""
    destino = origem.with_name(f"{prefixo}{sufixo}{origem.suffix}")
    n = 2
    while destino.exists():
        destino = origem.with_name(f"{prefixo}{sufixo}_{n}{origem.suffix}")
        n += 1
    origem.rename(destino)
    return {**resultado, "arquivo": str(destino)}
