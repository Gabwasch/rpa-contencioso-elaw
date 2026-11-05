"""
Pesquisa de tarefas + relatório de tarefas + re-checagem do status de UMA tarefa pelo ID.

Regras da tela (aprendidas no sistema real):
  * a tela RESTAURA os filtros da última pesquisa da sessão (inclusive um ID antigo e outro
    tipo de data) -> SEMPRE "Limpar Pesquisa" antes; senão o relatório sai filtrado por engano;
  * Status é obrigatório; período é obrigatório;
  * data por JS não chega ao servidor: é preciso DIGITAR (clique + Ctrl+A + digitação + Tab) e conferir;
  * Status/Tipo são checkboxes reais (selectCheckboxMenu): marcar pelo name funciona;
  * pesquisa recusada mostra um aviso e MANTÉM o resultado anterior na tela -> conferir os avisos
    em vez de confiar na tabela.
"""
from __future__ import annotations
from datetime import date
from pathlib import Path

from playwright.sync_api import Page

from .. import seletores as S
from ..conexao import url
from ..texto import norm
from ..util import clicar_e_navegar, escolher_opcao, esperar_pronto
from .relatorio import baixar_novo, gerar_no_modal, ids_existentes


class ErroPesquisa(RuntimeError):
    pass


STATUS_POR_NOME = {"pendentes": S.STATUS_PENDENTES, "atrasados": S.STATUS_ATRASADOS,
                   "concluidos": S.STATUS_CONCLUIDOS, "confirmados-em-atraso": S.STATUS_CONFIRMADOS_EM_ATRASO,
                   "cancelados": "3", "em-analise": "7"}

_MARCAR_JS = r"""([sufixo, valores]) => {
  let n = 0;
  document.querySelectorAll(`input[type=checkbox][name$="${sufixo}"]`).forEach(c => {
    c.checked = valores.includes(c.value); if (c.checked) n++; });
  return n; }"""
_OPCOES_JS = r"""(sufixo) => [...document.querySelectorAll(`input[type=checkbox][name$="${sufixo}"]`)]
  .map(c => { const l = document.querySelector(`label[for="${CSS.escape(c.id)}"]`);
              return [c.value, l ? l.innerText.trim() : '']; })"""
_RESULTADO_JS = r"""([body, growl]) => {
  const b = document.querySelector(body);
  const rows = b ? [...b.querySelectorAll(':scope > tr')] : [];
  const vazio = rows.length === 1 && rows[0].classList.contains('ui-datatable-empty-message');
  return {linhas: vazio ? 0 : rows.length,
          msgs: [...document.querySelectorAll(growl)].map(m => m.innerText.trim()).filter(Boolean)}; }"""


def resolver_tipos(page: Page, tipos: list[str]) -> list[str]:
    """Aceita o Tipo de Tarefa pelo value ('7101') ou pelo nome ('Anexar contestação', sem acento/caixa)."""
    disponiveis = page.evaluate(_OPCOES_JS, S.TAREFAS_CHK_TIPO)
    por_nome = {norm(rotulo): valor for valor, rotulo in disponiveis}
    valores = []
    for t in tipos:
        if t.isdigit():
            valores.append(t)
            continue
        v = por_nome.get(norm(t))
        if v is None:
            parecidos = [r for _, r in disponiveis if norm(t)[:8] in norm(r)][:5]
            raise ErroPesquisa(f"Tipo de tarefa '{t}' não existe no eLaw."
                               + (f" Parecidos: {'; '.join(parecidos)}" if parecidos else ""))
        valores.append(v)
    return valores


def _digitar_data(page: Page, seletor: str, valor: str, tentativas: int = 3) -> None:
    """Digita e CONFERE (com a tela re-renderizando, as primeiras teclas podem se perder)."""
    campo = page.locator(seletor)
    for _ in range(tentativas):
        campo.click()
        page.keyboard.press("Control+A")
        page.keyboard.type(valor, delay=15)
        page.keyboard.press("Tab")
        if campo.input_value() == valor:
            return
    raise ErroPesquisa(f"Não consegui preencher a data {valor} (ficou '{campo.input_value()}').")


def pesquisar(page: Page, status: list[str], tipos: list[str], inicio: date, fim: date,
              id_tarefa: str | None = None, tipo_data: str = "dataRegistrado") -> dict:
    """Aplica os filtros e pesquisa. Devolve {linhas, msgs}. Com `id_tarefa`, só aquela tarefa."""
    page.goto(url("agendamentoContenciosoList.elaw"), wait_until="domcontentloaded")
    esperar_pronto(page)
    clicar_e_navegar(page, S.TAREFAS_BTN_LIMPAR)          # a tela restaura a última pesquisa!
    tipos = resolver_tipos(page, tipos)
    if page.evaluate(_MARCAR_JS, [S.TAREFAS_CHK_STATUS, status]) != len(status):
        raise ErroPesquisa(f"Status não encontrados no filtro: {status}")
    if page.evaluate(_MARCAR_JS, [S.TAREFAS_CHK_TIPO, tipos]) != len(tipos):
        raise ErroPesquisa(f"Tipos de tarefa não encontrados no filtro: {tipos}")
    escolher_opcao(page, S.TAREFAS_COMBO_TIPO_DATA, S.TIPO_DATA[tipo_data])
    if id_tarefa:
        escolher_opcao(page, S.TAREFAS_COMBO_TIPO_PESQUISA, "ID")
        page.fill(S.TAREFAS_TXT, str(id_tarefa))
    _digitar_data(page, S.TAREFAS_DATA_INICIO, inicio.strftime("%d/%m/%Y"))
    _digitar_data(page, S.TAREFAS_DATA_FIM, fim.strftime("%d/%m/%Y"))
    clicar_e_navegar(page, S.TAREFAS_BTN_PESQUISAR)
    r = page.evaluate(_RESULTADO_JS, [S.TAREFAS_DT_BODY, S.GROWL])
    if r["msgs"]:   # pesquisa recusada: a tabela ainda mostra o resultado ANTERIOR
        raise ErroPesquisa("O eLaw recusou a pesquisa: " + " / ".join(r["msgs"]))
    return r


def status_da_tarefa(page: Page, id_tarefa: str, inicio: date, fim: date, tipo_data: str = "dataRegistrado") -> str:
    """Status REAL da tarefa: 'concluida' | 'pendente' | 'nao_encontrada'. Usado quando o robô não tem
    certeza se o Confirmar pegou (form demorou, erro depois do upload, linha sumiu da ficha)."""
    if pesquisar(page, [S.STATUS_CONCLUIDOS, S.STATUS_CONFIRMADOS_EM_ATRASO], [], inicio, fim,
                 id_tarefa, tipo_data)["linhas"]:
        return "concluida"
    if pesquisar(page, [S.STATUS_PENDENTES, S.STATUS_ATRASADOS], [], inicio, fim, id_tarefa, tipo_data)["linhas"]:
        return "pendente"
    return "nao_encontrada"


def gerar_relatorio(page: Page, pasta: Path, template: str, status: list[str], tipos: list[str],
                    inicio: date, fim: date, tipo_data: str = "dataRegistrado", timeout_s: int = 180) -> dict:
    """Pesquisa -> modal -> espera 'Meus Relatórios' -> baixa o arquivo da NOSSA solicitação."""
    ids_antes = ids_existentes(page)
    r = pesquisar(page, status, tipos, inicio, fim, tipo_data=tipo_data)
    if r["linhas"] == 0:
        return {"ok": True, "vazio": True, "arquivo": None, "motivo": "nenhuma tarefa com esses filtros"}
    id_solicitacao = gerar_no_modal(page, template, S.TAREFAS_BTN_EXCEL)
    return baixar_novo(page, pasta, ids_antes, id_solicitacao, timeout_s)
