"""
Fluxo de ESCRITA: anexar um documento avulso ao processo (aba Anexos -> "Novo Arquivo").

  ficha -> aba Anexos -> "Novo Arquivo" (modal em IFRAME) -> Tipo (clique real) ->
  upload por set_input_files (sem o diálogo do sistema operacional) -> Salvar

  * arquivo com o MESMO NOME já no processo -> JaAnexado (não envia de novo);
  * conferência pelo ID NOVO no GED (antes x depois), não pelo nome — o GED tira os acentos;
  * `ensaio=True`: vai até o Tipo escolhido e CANCELA (não envia nada).
"""
from __future__ import annotations
from pathlib import Path

from playwright.sync_api import Page

from .. import seletores as S
from ..util import escolher_opcao, esperar_pronto, frame_por_url, rotulo_da_opcao
from .concluir import JaAnexado
from .processo import abrir_processo, anexos_com_nome, listar_anexos


def anexar(page: Page, numero: str, pdf: Path, tipo_doc: str, ensaio: bool = False) -> dict:
    pdf = Path(pdf)
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    abrir_processo(page, numero)
    antes = listar_anexos(page)
    iguais = anexos_com_nome(antes, pdf.name)
    if iguais:
        raise JaAnexado(iguais)

    page.get_by_role("button", name=S.GED_BTN_NOVO_TXT).click()   # id auto-gerado: mirar pelo texto
    fr = frame_por_url(page, S.GED_IFRAME_HINT)
    if fr is None:
        raise RuntimeError("O modal 'Novo Arquivo' não abriu.")
    fr.wait_for_selector(S.GED_TIPO_INPUT, state="attached")

    def cancelar() -> None:
        fr.get_by_role("button", name="Cancelar").click()
        page.locator(".ui-dialog-mask").first.wait_for(state="detached", timeout=5_000)

    rotulo = rotulo_da_opcao(fr, S.GED_TIPO_INPUT, tipo_doc)
    if rotulo is None:
        cancelar()
        raise LookupError(f"Tipo de Documento {tipo_doc} não existe no modal 'Novo Arquivo'.")
    escolher_opcao(fr, S.GED_TIPO_INPUT, rotulo)
    if ensaio:
        cancelar()
        return {"ok": True, "ensaio": True, "tipo": rotulo, "anexos_antes": len(antes)}

    fr.set_input_files(S.GED_FILE_INPUT, str(pdf))
    fr.wait_for_selector(f"#docsStaging li:has-text('{pdf.name[:20]}')", timeout=15_000)
    fr.get_by_role("button", name="Salvar").click()
    page.locator(".ui-dialog-mask").first.wait_for(state="detached", timeout=15_000)
    esperar_pronto(page)
    ids_antes = {a["id"] for a in antes}
    page.wait_for_selector(S.GED_PRINCIPAL_BODY, state="attached", timeout=20_000)
    novos = [a for a in listar_anexos(page) if a["id"] not in ids_antes]
    novo = (anexos_com_nome(novos, pdf.name) or novos or [None])[0]
    return {"ok": novo is not None, "tipo": rotulo, "id_anexo": novo["id"] if novo else None, "anexo": novo}
