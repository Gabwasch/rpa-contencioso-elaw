"""
Fluxos de LEITURA do processo: buscar, abrir a ficha, ler as tarefas em aberto
(aba "Pauta e Andamento") e os anexos (aba "Anexos" / GED).
"""
from __future__ import annotations
import re

from playwright.sync_api import Page

from .. import seletores as S
from ..conexao import url
from ..regras import e_contestacao
from ..tarefas_xlsx import Tarefa
from ..texto import chave_nome, norm
from ..util import clicar_e_navegar, escolher_opcao, esperar_pronto, frame_por_url, indice_da_linha


class ProcessoNaoEncontrado(LookupError):
    pass


def buscar(page: Page, termo: str, por: str = S.TIPO_PESQUISA_NUMERO) -> list[dict]:
    """Pesquisa processos e devolve as linhas do resultado (não abre a ficha)."""
    page.goto(url("processoList.elaw"), wait_until="domcontentloaded")
    esperar_pronto(page)
    escolher_opcao(page, S.BUSCA_COMBO_TIPO, por)
    page.fill(S.BUSCA_TXT, termo)
    clicar_e_navegar(page, S.BUSCA_BTN_PESQUISAR)
    return page.eval_on_selector(S.BUSCA_DT_BODY, f"""body => [...body.querySelectorAll(':scope > tr')]
        .filter(tr => !tr.classList.contains('ui-datatable-empty-message'))
        .map(tr => {{ const td = [...tr.querySelectorAll(':scope > td')].map(c => c.innerText.trim());
                     return {{id: td[{S.COL_ID}], empresa: td[{S.COL_EMPRESA}], parte: td[{S.COL_PARTE}],
                              status: td[{S.COL_STATUS}], numero: td[{S.COL_NUMERO}]}}; }})""")


def abrir_processo(page: Page, numero: str) -> dict:
    """Busca pelo nº e clica em 'Abrir Processo' na linha certa -> ficha."""
    linhas = buscar(page, numero)
    n = next((i for i, l in enumerate(linhas) if re.sub(r"\D", "", l["numero"]) == re.sub(r"\D", "", numero)), -1)
    if n < 0:
        raise ProcessoNaoEncontrado(f"Processo {numero} não encontrado no eLaw.")
    clicar_e_navegar(page, S.BUSCA_BTN_ABRIR_N.format(n=n))
    return linhas[n]


def abrir_aba(page: Page, seletor_aba: str) -> None:
    page.locator(seletor_aba).first.click()
    esperar_pronto(page)


# ---------------------------------------------------------------- tarefas da ficha
_STATUS_ICONE = {"yellow": "Pendente", "red": "Atrasado", "orange": "A Vencer", "purple": "Em análise",
                 "green": "Concluído", "blue": "Cancelado"}
_LINHAS_TAREFAS_JS = r"""(sel) => {
  const body = document.querySelector(sel);
  if (!body) return [];
  return [...body.querySelectorAll(':scope > tr')].map(tr => {
    const td = [...tr.querySelectorAll(':scope > td')].map(c => c.innerText.replace(/\s+/g, ' ').trim());
    const img = tr.querySelector('img[src*="checkbox_"]');
    const cor = img ? ((img.getAttribute('src').match(/checkbox_(\w+)\./) || [])[1] || '') : '';
    return {cor, id: td[2] || '', prazo: td[4] || '', subtipo: td[6] || '', descricao: td[8] || ''};
  }); }"""


def tarefas_em_aberto(page: Page, numero: str) -> list[Tarefa]:
    """Tarefas em aberto lidas direto na ficha (sem relatório: segundos em vez de minutos).
    `data` fica vazia: na tabela a 'Data' é o PRAZO; a data de registro está no modal 'Ver'."""
    abrir_processo(page, numero)
    abrir_aba(page, S.ABA_PAUTA)
    page.wait_for_selector(S.DT_TAREFAS_BODY, state="attached")
    tarefas = []
    for r in page.evaluate(_LINHAS_TAREFAS_JS, S.DT_TAREFAS_BODY):
        if r["id"].isdigit():
            tarefas.append(Tarefa(len(tarefas) + 1, numero, r["subtipo"], _STATUS_ICONE.get(r["cor"], r["cor"]),
                                  r["id"], "", texto=f"{r['subtipo']} {r['descricao']}"))
    return tarefas


def data_registrado(page: Page, id_tarefa: str) -> str:
    """dd/mm/aaaa em que a tarefa entrou (modal 'Ver', que é um iframe). Supõe a aba de tarefas aberta."""
    n = indice_da_linha(page, S.DT_TAREFAS_BODY, id_tarefa)
    if n < 0:
        return ""
    page.locator(S.TAREFA_BTN_VER_N.format(n=n)).first.click()
    fr = frame_por_url(page, S.VER_IFRAME_HINT)
    texto = ""
    if fr is not None:
        fr.wait_for_selector("text=Registrado", timeout=10_000)
        texto = fr.evaluate("() => document.body.innerText")
        # o botão "Fechar" fica DENTRO do iframe; a máscara do modal bloqueia o próximo clique
        fr.get_by_role("button", name="Fechar").click()
    page.locator(".ui-dialog-mask").first.wait_for(state="detached", timeout=5_000)
    m = re.search(r"Registrado:\s*(\d{2}/\d{2}/\d{4})", texto)
    return m.group(1) if m else ""


# ---------------------------------------------------------------- anexos (GED)
_LISTAR_ANEXOS_JS = r"""(sel) => {
  const out = {};
  document.querySelectorAll(sel).forEach(body => {
    const hdr = [...body.closest('table').querySelectorAll('thead th')].map(h => h.innerText.trim());
    const iId = hdr.indexOf('ID'), iNome = hdr.indexOf('Nome do Arquivo'),
          iTipo = hdr.indexOf('Tipo de Documento'), iData = hdr.indexOf('Data');
    if (iId < 0 || iNome < 0) return;
    const tabela = body.id.split(':').slice(-2, -1)[0];
    body.querySelectorAll(':scope > tr').forEach(tr => {
      const td = [...tr.querySelectorAll(':scope > td')].map(c => c.innerText.trim());
      const id = td[iId];
      if (!id || !/^\d+$/.test(id)) return;
      const a = out[id] || (out[id] = {id, nome: td[iNome], tipo: iTipo >= 0 ? td[iTipo] : '',
                                       data: iData >= 0 ? td[iData] : '', tabelas: []});
      a.tabelas.push(tabela);
    });
  });
  return Object.values(out); }"""


def listar_anexos(page: Page) -> list[dict]:
    """Com a ficha aberta: aba Anexos (carregada por ajax) -> [{id, nome, tipo, data, tabelas}]."""
    abrir_aba(page, S.ABA_ANEXOS)
    page.wait_for_selector(S.GED_PRINCIPAL_BODY, state="attached", timeout=20_000)   # tempo fixo não basta
    return page.evaluate(_LISTAR_ANEXOS_JS, S.GED_TABELAS_BODY)


def anexos_com_nome(anexos: list[dict], nome_arquivo: str) -> list[dict]:
    alvo = chave_nome(nome_arquivo)
    return [a for a in anexos if chave_nome(a["nome"]) == alvo]


_TIPOS_CONTESTACAO = {"defesa", "contestacao", "contestacao ia"}


def contestacoes_no_processo(anexos: list[dict]) -> list[dict]:
    """Anexos que JÁ são a contestação, mesmo com outro nome: tipo Defesa/Contestação ou nome de contestação."""
    return [a for a in anexos if norm(a.get("tipo")) in _TIPOS_CONTESTACAO or e_contestacao(a.get("nome") or "")]


def orfao(anexo: dict) -> bool:
    """Só está na tabela principal (sem vínculo com tarefa): órfão de conclusão que falhou OU anexo
    legítimo feito pela aba Anexos — por isso só sinalizamos, nunca apagamos."""
    return anexo["tabelas"] == [S.GED_TABELA_PRINCIPAL]
