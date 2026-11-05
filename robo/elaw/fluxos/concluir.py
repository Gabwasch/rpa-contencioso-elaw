"""
Fluxo de ESCRITA: concluir uma tarefa no form "Confirmar agendamento".

  ficha -> aba "Pauta e Andamento" -> linha da tarefa (pelo ID + assunto) -> ícone Confirmar
  -> (mesma aba) agendamentoContenciosoConfirm -> preencher -> #btnConfirmaSim -> volta à ficha

Proteções (cada uma nasceu de um problema real):
  * o UPLOAD grava no GED NA HORA, antes do Confirmar. Se a conclusão falhar depois, o arquivo fica
    ÓRFÃO e re-tentar DUPLICA -> antes de enviar, lista os anexos do processo: mesmo nome (ou uma
    contestação já anexada) -> JaAnexado, não envia; depois do upload, qualquer exceção leva o
    `id_anexo` junto, para a auditoria dizer o que limpar;
  * com anexo, o sistema demora para sair do form -> espera até 30 s antes de concluir "não pegou";
  * nunca confirmar com campo obrigatório vazio (trava antes do clique).
"""
from __future__ import annotations
import re
from pathlib import Path

from playwright.sync_api import Page

from .. import seletores as S
from ..texto import chave_nome
from ..util import escolher_opcao, esperar_pronto, indice_da_linha, rotulo_da_opcao
from .processo import abrir_aba, abrir_processo, anexos_com_nome, contestacoes_no_processo, listar_anexos, orfao


class FormIncompleto(RuntimeError):
    pass


class TarefaNaoEncontrada(LookupError):
    """A linha da tarefa não está na ficha (talvez alguém já a concluiu)."""


class JaAnexado(RuntimeError):
    """O processo já tem o arquivo (ou uma contestação). Não reenviamos — duplicaria o documento."""

    def __init__(self, anexos: list[dict]):
        self.anexos = anexos
        desc = "; ".join(f"{a['id']} ({a['tipo'] or 'sem tipo'}, {a['data']}"
                         f"{', sem vínculo com tarefa' if orfao(a) else ''})" for a in anexos)
        super().__init__(f"o processo já tem o anexo: {desc}")


def _confirmar_e_aguardar(page: Page, timeout_s: int = 30) -> dict:
    """Clica Confirmar e espera SAIR do form. Se ficar no form, devolve ok=False + avisos da tela."""
    page.click(S.CONFIRM_BTN_CONFIRMAR)
    try:
        page.wait_for_url(lambda u: S.CONFIRM_URL_HINT not in u, timeout=timeout_s * 1000)
    except Exception:
        pass
    esperar_pronto(page)
    ok = S.CONFIRM_URL_HINT not in page.url
    avisos = [] if ok else [t.strip() for t in page.locator(S.GROWL).all_inner_texts() if t.strip()]
    return {"ok": ok, "url": page.url, "avisos": avisos}


def abrir_form(page: Page, numero: str, assunto: str, id_tarefa: str | None = None,
               ficha_aberta: bool = False) -> None:
    """Abre o form da tarefa. Com `id_tarefa`, casa a linha por ID + assunto (evita homônimas)."""
    if not ficha_aberta:
        abrir_processo(page, numero)
    abrir_aba(page, S.ABA_PAUTA)
    page.wait_for_selector(S.DT_TAREFAS_BODY, state="attached")
    n = indice_da_linha(page, S.DT_TAREFAS_BODY, assunto, id_tarefa or "")
    if n < 0:
        raise TarefaNaoEncontrada(f"Tarefa '{assunto}'{f' (ID {id_tarefa})' if id_tarefa else ''} não está "
                                  "entre as tarefas em aberto da ficha.")
    with page.expect_navigation(wait_until="load"):
        page.locator(S.TAREFA_BTN_CONFIRMAR_N.format(n=n)).first.click()
    esperar_pronto(page)
    if S.CONFIRM_URL_HINT not in page.url:
        raise TarefaNaoEncontrada(f"O form de confirmação não abriu (o eLaw voltou para {page.url}).")


def _id_anexo_enviado(page: Page, nome_arquivo: str, tentativas: int = 20) -> str | None:
    """ID que o GED deu ao arquivo recém-enviado (linha da área de upload do form)."""
    alvo = chave_nome(Path(nome_arquivo).stem)
    for _ in range(tentativas):
        linhas = page.eval_on_selector_all(
            S.CONFIRM_UPLOAD_LINHAS,
            "trs => trs.filter(r => r.offsetParent !== null).map(r => r.innerText.replace(/\\s+/g, ' ').trim())")
        for txt in linhas:
            m = re.match(r"(\d+)\s", txt)
            if m and alvo in chave_nome(txt):
                return m.group(1)
        page.wait_for_timeout(500)
    return None


def _escolher_por_valor(page: Page, seletor: str, valor: str) -> str:
    rotulo = rotulo_da_opcao(page, seletor, valor)
    if rotulo is None:
        raise FormIncompleto(f"Tipo de Documento {valor} não é aceito neste formulário.")
    escolher_opcao(page, seletor, rotulo)
    return rotulo


def concluir_sem_anexo(page: Page, numero: str, assunto: str, justificativa: str,
                       id_tarefa: str | None = None) -> dict:
    """'Anexar defesa? = Não' + justificativa ('Já anexada' / 'Prazo de contestação em curso')."""
    abrir_form(page, numero, assunto, id_tarefa)
    escolher_opcao(page, S.CONFIRM_COMBO_PRINCIPAL, "Não")
    # a justificativa tem id dinâmico: acha o select que tem essa opção
    sel_id = page.evaluate("""(j) => { const s = [...document.querySelectorAll('select[id$="_input"]')]
                                 .find(s => [...s.options].some(o => o.text.trim() === j)); return s ? s.id : null; }""",
                           justificativa)
    if sel_id is None:
        raise FormIncompleto(f"Justificativa '{justificativa}' não existe neste formulário.")
    escolher_opcao(page, f'[id="{sel_id}"]', justificativa)   # (confere a seleção; senão levanta)
    return _confirmar_e_aguardar(page)


def concluir_com_anexo(page: Page, numero: str, assunto: str, pdf: Path, tipo_doc: str,
                       id_tarefa: str | None = None, checar_duplicado: bool = True) -> dict:
    """'Anexar defesa? = Sim' + Tipo + upload -> Confirmar. Ver as proteções no topo do módulo."""
    pdf = Path(pdf)
    if not pdf.exists():
        raise FileNotFoundError(pdf)
    abrir_processo(page, numero)
    if checar_duplicado:
        anexos = listar_anexos(page)
        iguais = anexos_com_nome(anexos, pdf.name) or contestacoes_no_processo(anexos)
        if iguais:
            raise JaAnexado(iguais)
    abrir_form(page, numero, assunto, id_tarefa, ficha_aberta=True)
    escolher_opcao(page, S.CONFIRM_COMBO_PRINCIPAL, "Sim")
    _escolher_por_valor(page, S.CONFIRM_TIPOS_DOC, tipo_doc)
    page.set_input_files(S.CONFIRM_FILE_INPUT, str(pdf))   # sem diálogo do sistema operacional
    id_anexo = _id_anexo_enviado(page, pdf.name)          # a partir daqui o arquivo JÁ está no GED
    try:
        if id_anexo is None:
            raise FormIncompleto("O upload não devolveu o ID do arquivo no GED.")
        if page.eval_on_selector(S.CONFIRM_TIPOS_DOC, "el => el.value") != tipo_doc:
            raise FormIncompleto("Tipo de Documento não ficou preenchido.")   # trava: nunca confirmar vazio
        r = _confirmar_e_aguardar(page)
    except Exception as e:
        e.id_anexo = id_anexo
        raise
    r["id_anexo"] = id_anexo
    return r


RESULTADOS_AUDIENCIA = {True: ("Frutífera", "Infrutífera"),
                        False: ("Audiência redesignada", "Ausencia do autor", "Conciliação")}


def concluir_audiencia(page: Page, numero: str, assunto: str, realizada: bool, resultado: str,
                       ata: Path | None = None, tipo_ata: str = "", id_tarefa: str | None = None) -> dict:
    """'Audiência realizada? = Sim|Não' + 'Resultado' (+ ata opcional). Mesmas proteções do upload."""
    if resultado not in RESULTADOS_AUDIENCIA[realizada]:
        raise ValueError(f"Resultado '{resultado}' inválido; válidos: {RESULTADOS_AUDIENCIA[realizada]}")
    abrir_processo(page, numero)
    if ata is not None:
        iguais = anexos_com_nome(listar_anexos(page), Path(ata).name)
        if iguais:
            raise JaAnexado(iguais)
    abrir_form(page, numero, assunto, id_tarefa, ficha_aberta=True)
    escolher_opcao(page, S.CONFIRM_COMBO_PRINCIPAL, "Sim" if realizada else "Não")
    seletor_resultado = (S.CONFIRM_RESULTADO_AUDIENCIA if realizada
                         else 'select[id$="_input"]:has(option:text-is("Audiência redesignada"))')
    escolher_opcao(page, seletor_resultado, resultado)   # trava: confere a seleção
    id_anexo = None
    try:
        if ata is not None:
            _escolher_por_valor(page, S.CONFIRM_TIPO_ATA, tipo_ata)
            page.set_input_files(S.CONFIRM_FILE_INPUT, str(ata))
            id_anexo = _id_anexo_enviado(page, Path(ata).name)
            if id_anexo is None:
                raise FormIncompleto("O upload da ata não devolveu o ID do arquivo no GED.")
        r = _confirmar_e_aguardar(page)
    except Exception as e:
        e.id_anexo = id_anexo
        raise
    r["id_anexo"] = id_anexo
    return r
