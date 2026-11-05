"""
Interface web "parecida com o eLaw" (JSF/PrimeFaces) — só o necessário para o robô
rodar ponta a ponta e para as armadilhas reais aparecerem:

  * ids com trecho j_id_* sorteado a cada início do servidor (só seletor por SUFIXO funciona);
  * selects que só registram com clique real (o <select> oculto não tem name);
  * tela de tarefas que RESTAURA a última pesquisa da sessão (precisa "Limpar Pesquisa");
  * relatório em modal (IFRAME), gerado de forma ASSÍNCRONA, entregue em "Meus Relatórios"
    (que abre vazio e com o filtro de data de ontem), junto com relatórios antigos;
  * upload no form de conclusão grava no GED NA HORA (antes do Confirmar);
  * Confirmar com anexo demora alguns segundos; um cenário falha de propósito;
  * sessão expirada -> tudo redireciona para a tela de login.
"""
from __future__ import annotations
import asyncio
import html
import io
import re
import secrets
from datetime import date, datetime

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .estado import (Estado, JUSTIFICATIVAS, STATUS_COR, STATUS_FILTRO, STATUS_ROTULO, TEMPLATES, TIPOS_ATA,
                     TIPOS_DOC_CONCLUSAO, TIPOS_GED, br)

COOKIE = "ELAWSESSID"
TIPO_CONTESTACAO, TIPO_AUDIENCIA = "7101", "7102"


def esc(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def _data_br(txt: str) -> date | None:
    try:
        return datetime.strptime((txt or "").strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


def _so_digitos(txt: str) -> str:
    return re.sub(r"\D", "", txt or "")


# ------------------------------------------------------------------------------- componentes
def combo(wid: str, opcoes: list[tuple[str, str]], valor: str = "", nome: str = "") -> str:
    """selectOneMenu: div visível + <select> oculto SEM name + input hidden (o que vai ao servidor)."""
    rotulo = next((l for v, l in opcoes if v == valor), opcoes[0][1] if opcoes else "")
    opts = "".join(f'<option value="{esc(v)}"{" selected" if v == valor else ""}>{esc(l)}</option>'
                   for v, l in opcoes)
    itens = "".join(f'<li class="ui-selectonemenu-item" data-label="{esc(l)}" data-value="{esc(v)}">{esc(l)}</li>'
                    for v, l in opcoes)
    nome_attr = f' name="{esc(nome)}"' if nome else ""
    return (f'<div id="{wid}" class="ui-selectonemenu"><span class="ui-selectonemenu-label">{esc(rotulo)}</span>'
            f'<span class="ui-selectonemenu-trigger">&#9662;</span>'
            f'<select id="{wid}_input" tabindex="-1" aria-hidden="true">{opts}</select>'
            f'<input type="hidden" id="{wid}_valor"{nome_attr} value="{esc(valor)}"></div>'
            f'<div id="{wid}_panel" class="ui-selectonemenu-panel" hidden><ul>{itens}</ul></div>')


def checkmenu(wid: str, nome: str, opcoes: list[tuple[str, str]], marcados: list[str], form_id: str) -> str:
    """selectCheckboxMenu: checkboxes reais (com name) num painel que vai para o <body>
    (por isso o atributo form=)."""
    itens = "".join(
        f'<label for="{wid}:{i}"><input type="checkbox" id="{wid}:{i}" name="{esc(nome)}" value="{esc(v)}" '
        f'form="{form_id}"{" checked" if v in marcados else ""}> {esc(l)}</label>'
        for i, (v, l) in enumerate(opcoes))
    return (f'<div id="{wid}" class="ui-selectcheckboxmenu"><span class="ui-selectcheckboxmenu-label">Selecione</span>'
            f'<span class="ui-selectcheckboxmenu-trigger">&#9662;</span></div>'
            f'<div id="{wid}_panel" class="ui-selectcheckboxmenu-panel" hidden>{itens}</div>')


def icone_status(cod: str) -> str:
    return (f'<img class="status" src="/static/icones/checkbox_{STATUS_COR.get(cod, "yellow")}.png" '
            f'title="{esc(STATUS_ROTULO.get(cod, ""))}" alt="">')


SVG_CORES = {"green": "#2e9e5b", "yellow": "#e6b32e", "red": "#d6453d", "blue": "#3b7dd8",
             "orange": "#ee8a2a", "purple": "#8a5cc7"}


def criar_router(estado: Estado) -> APIRouter:
    r = APIRouter()
    P = estado.prefixos

    # ------------------------------------------------------------------- sessão e layout
    def sessao(request: Request) -> dict | None:
        return estado.sessoes.get(request.cookies.get(COOKIE, ""))

    def ir_login() -> RedirectResponse:
        return RedirectResponse("/login.elaw", status_code=303)

    def growl_html(s: dict | None) -> str:
        if not s or not s["growl"]:
            return ""
        itens = "".join(f'<div class="ui-growl-item {"erro" if erro else ""}"><div class="ui-growl-message">'
                        f'{esc(msg)}</div></div>' for msg, erro in s["growl"])
        s["growl"] = []
        return f'<div class="ui-growl">{itens}</div>'

    def pagina(titulo: str, corpo: str, s: dict | None = None, dialogo: bool = False, scripts: str = "",
               status: int = 200, cru: bool = False) -> HTMLResponse:
        topo = ""
        if s and not dialogo:
            topo = (f'<header class="topo"><div class="logo">eLaw<small>mock de demonstração</small></div>'
                    f'<nav><a href="/homePage.elaw">Início</a><a href="/processoList.elaw">Processos</a>'
                    f'<a href="/agendamentoContenciosoList.elaw">Tarefas</a><a href="/__mock/cenarios">Cenários</a></nav>'
                    f'<div class="direita"><a href="#" class="maleta" id="{P["topo"]}:maleta" title="Meus Relatórios">'
                    f'<span class="pi pi-briefcase">&#128188;</span></a>'
                    f'<span class="usuario">{esc(estado.usuario["nome"])} · <a href="/logout.elaw">Sair</a></span></div>'
                    f'<div class="notification-panel" hidden><a class="notification-summary" '
                    f'href="/userElawReportRequestList.elaw?etoken={s["etoken"]}">Meus Relatórios</a>'
                    f'<a class="notification-summary" href="#">Notificações (0)</a></div></header>')
        faixa = "" if dialogo else '<div class="faixa-mock">AMBIENTE DE DEMONSTRAÇÃO — TODOS OS DADOS SÃO FICTÍCIOS</div>'
        doc = (f'<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><title>{esc(titulo)} · eLaw (mock)</title>'
               f'<link rel="stylesheet" href="/static/style.css"><script src="/static/pf.js"></script></head>'
               f'<body class="{"dialogo" if dialogo else ""}">{faixa}{topo}{growl_html(s)}'
               f'{corpo if cru else f"<main>{corpo}</main>"}{scripts}</body></html>')
        return HTMLResponse(doc, status_code=status)

    def flash(s: dict, msg: str, erro: bool = False) -> None:
        s["growl"].append((msg, erro))

    def voltar(url: str) -> RedirectResponse:
        return RedirectResponse(url, status_code=303)

    # ------------------------------------------------------------------- ícones e utilidades
    @r.get("/static/icones/{nome}")
    async def icone(nome: str):
        m = re.match(r"checkbox_(\w+)\.png$", nome)
        if m:
            cor = SVG_CORES.get(m.group(1), "#999")
            svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"><rect x="1" y="1" width="12" '
                   f'height="12" rx="3" fill="{cor}"/></svg>')
        else:   # clip.png
            svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"><path '
                   'd="M16.5 6.5v10a4.5 4.5 0 0 1-9 0V5a3 3 0 0 1 6 0v10.5a1.5 1.5 0 0 1-3 0V6.5" fill="none" '
                   'stroke="#2d5a88" stroke-width="2" stroke-linecap="round"/></svg>')
        return Response(svg, media_type="image/svg+xml")

    @r.get("/")
    async def raiz():
        return voltar("/homePage.elaw")

    # ------------------------------------------------------------------- login
    def tela_login(msg: str = "") -> HTMLResponse:
        aviso = f'<div class="aviso">{esc(msg)}</div>' if msg else ""
        corpo = (f'<div class="login-fundo"><div class="login-card"><h1>eLaw</h1>'
                 f'<p class="sub">Gestão do contencioso · ambiente de demonstração</p>{aviso}'
                 f'<button type="button" class="btn sec" id="{P["login"]}:btnSso" onclick="document.getElementById'
                 f'(\'msgSso\').hidden=false">Entrar com SSO corporativo</button>'
                 f'<p id="msgSso" class="aviso" hidden>No mundo real, aqui o operador passa pelo SSO/MFA corporativo. '
                 f'No mock, use usuário e senha abaixo.</p>'
                 f'<div class="ou">ou com credenciais locais</div>'
                 f'<form method="post" action="/login.elaw">'
                 f'<div class="campo"><label for="{P["login"]}:username">Usuário</label>'
                 f'<input id="{P["login"]}:username" name="username" autocomplete="off"></div>'
                 f'<div class="campo"><label for="{P["login"]}:password">Senha</label>'
                 f'<input id="{P["login"]}:password" name="password" type="password"></div>'
                 f'<button class="btn" id="{P["login"]}:btnAcessar" type="submit">Acessar</button></form>'
                 f'<div class="dica">Usuário <b>operador</b> · senha <b>demo123</b><br>'
                 f'O robô NUNCA usa esta tela: quem faz login é o operador.</div></div></div>')
        return pagina("Login", corpo, cru=True)

    @r.get("/login.elaw")
    async def login_get():
        return tela_login()

    @r.post("/login.elaw")
    async def login_post(request: Request):
        f = await request.form()
        if f.get("username") != estado.usuario["login"] or f.get("password") != estado.usuario["senha"]:
            return tela_login("Usuário ou senha inválidos.")
        sid = estado.nova_sessao()
        resp = voltar("/homePage.elaw")
        resp.set_cookie(COOKIE, sid, httponly=True, samesite="lax")
        return resp

    @r.get("/logout.elaw")
    async def logout(request: Request):
        estado.sessoes.pop(request.cookies.get(COOKIE, ""), None)
        resp = ir_login()
        resp.delete_cookie(COOKIE)
        return resp

    @r.get("/homePage.elaw")
    async def home(request: Request):
        if (s := sessao(request)) is None:
            return ir_login()
        abertas = sum(1 for t in estado.tarefas.values() if t["situacao"] == "aberta")
        corpo = (f'<h1>Bem-vindo(a), {esc(estado.usuario["nome"])}</h1><div class="cards">'
                 f'<a class="card" href="/processoList.elaw"><b>Contencioso</b>{len(estado.processos)} processos fictícios</a>'
                 f'<a class="card" href="/agendamentoContenciosoList.elaw"><b>Tarefas</b>{abertas} tarefas em aberto</a>'
                 f'<a class="card" href="/__mock/cenarios"><b>Cenários do mock</b>o que cada processo demonstra</a></div>')
        return pagina("Início", corpo, s)

    # ------------------------------------------------------------------- busca de processos
    def buscar_processos(tipo: str, texto: str) -> list[int]:
        texto = (texto or "").strip()
        if not texto:
            return sorted(estado.processos)
        achados = []
        for p in estado.processos.values():
            if tipo == "numero" and _so_digitos(texto) and _so_digitos(texto) in _so_digitos(p["numero"]):
                achados.append(p["id"])
            elif tipo == "id" and texto == str(p["id"]):
                achados.append(p["id"])
            elif tipo == "geral" and (texto.casefold() in p["numero"].casefold()
                                      or texto.casefold() in p["parte_contraria"].casefold()):
                achados.append(p["id"])
        return achados

    @r.get("/processoList.elaw")
    async def processo_list(request: Request):
        if (s := sessao(request)) is None:
            return ir_login()
        b, pb = s["busca"], P["busca"]
        tipos = [("geral", "Geral"), ("numero", "Número do Processo"), ("id", "ID"), ("parte", "Parte")]
        linhas = ""
        if b["resultado"] is not None:
            for n, pid in enumerate(b["resultado"]):
                p = estado.processos[pid]
                linhas += (f'<tr data-ri="{n}"><td><a class="acao" id="{pb}:dtProcessoResults:{n}:btnProcesso" '
                           f'title="Abrir Processo" href="/processoView.elaw?id={pid}">&#128269;</a>'
                           f'<a class="acao" id="{pb}:dtProcessoResults:{n}:btnEditar" title="Editar" href="#">&#9998;</a></td>'
                           f'<td>{icone_status("1")}</td><td>{pid}</td><td>{esc(p["empresa"])}</td>'
                           f'<td>{esc(p["parte_contraria"])}</td><td>{esc(p["escritorio"])}</td><td>{esc(p["status"])}</td>'
                           f'<td>{esc(p["numero"])}</td></tr>')
            if not b["resultado"]:
                linhas = '<tr class="ui-datatable-empty-message"><td colspan="8">Nenhum registro encontrado.</td></tr>'
            qtd = f'<div class="ui-paginator-current">{len(b["resultado"])} registro(s) encontrado(s)</div>'
        else:
            qtd = ""
        corpo = (f'<h1>Processos</h1><div class="cartao"><form method="post" id="{pb}:formBusca" class="filtros">'
                 f'<div class="campo"><label>Tipo de pesquisa</label>'
                 f'{combo(f"{pb}:comboTipoPesquisa", tipos, b["tipo"], "tipo")}</div>'
                 f'<div class="campo"><label>Pesquise por aqui</label>'
                 f'<input id="{pb}:txtSearch" name="texto" value="{esc(b["texto"])}"></div>'
                 f'<div class="barra-botoes"><button class="btn" id="{pb}:btnPesquisar" name="acao" value="pesquisar">Pesquisar</button>'
                 f'<button class="btn sec" id="{pb}:btnLimparPesquisa" name="acao" value="limpar">Limpar Pesquisa</button></div>'
                 f'</form></div><div class="cartao"><table class="ui-datatable" id="{pb}:dtProcessoResults"><thead><tr>'
                 f'<th></th><th>Farol</th><th>ID</th><th>Empresa</th><th>Parte Contrária</th><th>Escritório Externo</th>'
                 f'<th>Status</th><th>Número do Processo</th></tr></thead>'
                 f'<tbody id="{pb}:dtProcessoResults_data">{linhas}</tbody></table>{qtd}</div>')
        return pagina("Processos", corpo, s)

    @r.post("/processoList.elaw")
    async def processo_list_post(request: Request):
        if (s := sessao(request)) is None:
            return ir_login()
        f = await request.form()
        if f.get("acao") == "limpar":
            s["busca"] = {"tipo": "numero", "texto": "", "resultado": None}
        else:
            tipo, texto = f.get("tipo") or "geral", f.get("texto") or ""
            s["busca"] = {"tipo": tipo, "texto": texto, "resultado": buscar_processos(tipo, texto)}
        return voltar("/processoList.elaw")

    # ------------------------------------------------------------------- ficha do processo
    def tabela_tarefas_ficha(pid: int) -> str:
        pp = P["pauta"]
        abertas = [t for t in estado.tarefas_do_processo(pid) if t["situacao"] == "aberta"]
        linhas = ""
        for n, t in enumerate(abertas):
            st = estado.status_tarefa(t)
            linhas += (f'<tr data-ri="{n}"><td>'
                       f'<a class="acao" id="{pp}:dtAgendamentoResults:{n}:verAgendamentoBtn" title="Ver" href="#" '
                       f'onclick="PF.abrirDialogo(\'/dialogs/agendamentoContenciosoView.elaw?id={t["id"]}\',\'Tarefa\',560);return false;">&#128269;</a>'
                       f'<a class="acao" id="{pp}:dtAgendamentoResults:{n}:confirmAgendamentoBtn" title="Confirmar" '
                       f'href="/agendamentoContenciosoConfirm.elaw?id={t["id"]}">&#10004;</a>'
                       f'<a class="acao" id="{pp}:dtAgendamentoResults:{n}:prorrogarAgendamentoBtn" title="Prorrogar" href="#">&#128197;</a>'
                       f'</td><td>{icone_status(st)}</td><td>{t["id"]}</td><td>{t["anterior"] or ""}</td>'
                       f'<td>{br(t["prazo"])}</td><td>ALERTA</td><td>{esc(estado.subtipo(t))}</td>'
                       f'<td>{esc(t["responsavel"])}</td><td>{esc(t["descricao"])}</td></tr>')
        if not linhas:
            linhas = '<tr class="ui-datatable-empty-message"><td colspan="9">Nenhum registro encontrado.</td></tr>'
        return (f'<h3>Tarefas em aberto</h3><table class="ui-datatable" id="{pp}:dtAgendamentoResults"><thead><tr>'
                f'<th>Ações</th><th>Status</th><th>ID da Tarefa</th><th>ID Vinculado</th><th>Data</th><th>Tipo</th>'
                f'<th>Subtipo</th><th>Responsável</th><th>Descrição</th></tr></thead>'
                f'<tbody id="{pp}:dtAgendamentoResults_data">{linhas}</tbody></table>')

    @r.get("/processoView.elaw")
    async def processo_view(request: Request, id: int = 0):
        if (s := sessao(request)) is None:
            return ir_login()
        p = estado.processos.get(id)
        if p is None:
            flash(s, "Processo não encontrado.", True)
            return voltar("/processoList.elaw")
        dados = "".join(f"<div><b>{esc(k)}</b>{esc(v)}</div>" for k, v in (
            ("ID", p["id"]), ("Número do Processo", p["numero"]), ("Empresa", p["empresa"]),
            ("Parte Contrária", p["parte_contraria"]), ("Escritório Externo", p["escritorio"]),
            ("Área do Direito", p["area"]), ("Estado", p["uf"]), ("Status", p["status"])))
        corpo = (f'<h1>Processo {esc(p["numero"])}</h1>'
                 f'<div class="barra-botoes" style="margin-bottom:14px"><a class="btn sec" id="btnVoltar" href="/processoList.elaw">Voltar</a>'
                 f'<button class="btn sec" id="btnEditar" type="button">Editar</button>'
                 f'<button class="btn sec" id="btnTrocarStatus" type="button">Trocar Status</button></div>'
                 f'<ul class="ui-tabs-nav"><li class="ui-state-active"><a href="#tabViewProcesso:dadosProcesso">Dados Processo</a></li>'
                 f'<li><a href="#tabViewProcesso:agendamentosAndamentos">Pauta e Andamento</a></li>'
                 f'<li><a href="#tabViewProcesso:files">Anexos</a></li>'
                 f'<li><a href="#tabViewProcesso:auditoria">Auditoria</a></li></ul>'
                 f'<div class="ui-tabs-panel" id="tabViewProcesso:dadosProcesso"><div class="grade">{dados}</div></div>'
                 f'<div class="ui-tabs-panel" id="tabViewProcesso:agendamentosAndamentos" hidden>{tabela_tarefas_ficha(id)}</div>'
                 f'<div class="ui-tabs-panel" id="tabViewProcesso:files" hidden data-lazy="/processoView/anexos?id={id}"></div>'
                 f'<div class="ui-tabs-panel" id="tabViewProcesso:auditoria" hidden><p>Sem registros de auditoria no mock.</p></div>')
        scripts = ('<script>PF.recarregarAnexos = function(){ PF.fecharDialogo(); '
                   'PF.carregar(document.getElementById("tabViewProcesso:files")); };</script>')
        return pagina("Processo", corpo, s, scripts=scripts)

    def tabela_ged(sufixo: str, anexos: list[dict]) -> str:
        pg = P["ged"]
        linhas = "".join(
            f'<tr data-ri="{n}"><td><input type="checkbox"></td><td>{a["id"]}</td><td>{esc(a["nome"])}</td>'
            f'<td>{esc(a["tipo"])}</td><td>{esc(a["tamanho"])}</td><td>{br(a["data"])}</td><td>{esc(a["usuario"])}</td>'
            f'<td><a class="acao" title="Baixar" href="#">&#11015;</a></td></tr>' for n, a in enumerate(anexos))
        if not linhas:
            linhas = '<tr class="ui-datatable-empty-message"><td colspan="8">Nenhum registro encontrado.</td></tr>'
        return (f'<table class="ui-datatable" id="{pg}:{sufixo}:GedEFileViewDt"><thead><tr><th></th><th>ID</th>'
                f'<th>Nome do Arquivo</th><th>Tipo de Documento</th><th>Tamanho</th><th>Data</th><th>Usuário</th><th></th>'
                f'</tr></thead><tbody id="{pg}:{sufixo}:GedEFileViewDt_data">{linhas}</tbody></table>')

    @r.get("/processoView/anexos")
    async def anexos_fragmento(request: Request, id: int = 0):
        if (s := sessao(request)) is None:
            return ir_login()
        p = estado.processos.get(id)
        if p is None:
            return HTMLResponse("<p>Processo não encontrado.</p>", status_code=404)
        anexos = sorted(p["anexos"], key=lambda a: a["id"])
        vinculados = [a for a in anexos if a["tarefa_id"]]
        return HTMLResponse(
            f'<div class="barra-botoes"><button type="button" class="btn" id="{P["ged"]}:{estado.jid_aleatorio()}" '
            f'onclick="PF.abrirDialogo(\'/dialogs/ged/gedEFileUpload.elaw?processo={id}\',\'Novo Arquivo\',620)">Novo Arquivo</button>'
            f'<button type="button" class="btn sec" id="{P["ged"]}:{estado.jid_aleatorio()}">Baixar Selecionados</button></div>'
            f'<h3>Anexos do Processo</h3>{tabela_ged("gedEFileDataTable", anexos)}'
            f'<h3>Arquivos vinculados a tarefas e formulários</h3>{tabela_ged("gedEFileEFVDataTable", vinculados)}')

    @r.get("/dialogs/agendamentoContenciosoView.elaw")
    async def ver_tarefa(request: Request, id: int = 0):
        if (s := sessao(request)) is None:
            return ir_login()
        t = estado.tarefas.get(id)
        if t is None:
            return pagina("Tarefa", "<p>Tarefa não encontrada.</p>", s, dialogo=True, status=404)
        corpo = (f'<h2>Tarefa {t["id"]}</h2><div class="grade">'
                 f'<div><b>Tipo</b>ALERTA</div><div><b>Subtipo</b>{esc(estado.subtipo(t))}</div>'
                 f'<div><b>Status</b>{esc(STATUS_ROTULO[estado.status_tarefa(t)])}</div>'
                 f'<div><b>Prazo</b>{br(t["prazo"])}</div><div><b>Responsável</b>{esc(t["responsavel"])}</div>'
                 f'<div><b>Tarefa Anterior</b>{t["anterior"] or "-"}</div></div>'
                 f'<p style="margin-top:16px">Registrado: {br(t["registrado"])}</p>'
                 f'<div class="barra-botoes"><button type="button" class="btn sec" onclick="PF.fecharEsteDialogo()">Fechar</button></div>')
        return pagina("Tarefa", corpo, s, dialogo=True)

    # ------------------------------------------------------------------- GED "Novo Arquivo" (modal)
    @r.get("/dialogs/ged/gedEFileUpload.elaw")
    async def ged_dialogo(request: Request, processo: int = 0):
        if (s := sessao(request)) is None:
            return ir_login()
        pd = P["dlg"]
        tipos = [("", "Selecione")] + list(TIPOS_GED.items())
        corpo = (f'<div class="campo"><label>Tipo de Documento (*)</label>{combo(f"{pd}:eFileTipoCombo", tipos)}</div>'
                 f'<div class="campo"><label>Arquivo</label><label class="btn sec">+ Selecionar '
                 f'<input type="file" id="{pd}:uploadGedEFile_input" accept=".pdf" hidden></label></div>'
                 f'<h3>Documentos</h3><ul id="docsStaging"><li><i>nenhum arquivo selecionado</i></li></ul>'
                 f'<p id="erroGed" class="aviso" hidden></p>'
                 f'<div class="barra-botoes"><button type="button" class="btn" id="{pd}:{estado.jid_aleatorio()}" onclick="salvar()">Salvar</button>'
                 f'<button type="button" class="btn sec" id="{pd}:{estado.jid_aleatorio()}" onclick="PF.fecharEsteDialogo()">Cancelar</button></div>')
        scripts = f"""<script>
let tokenStaging = null;
document.getElementById("{pd}:uploadGedEFile_input").addEventListener("change", async (ev) => {{
  const f = ev.target.files[0]; if (!f) return;
  const fd = new FormData(); fd.append("arquivo", f);
  PF.ocupado(true);
  const r = await fetch("/ged/staging", {{method: "POST", body: fd}});
  const j = await r.json(); PF.ocupado(false);
  tokenStaging = j.token;
  const li = document.createElement("li"); li.textContent = j.nome + " (" + j.tamanho + ")";
  const ul = document.getElementById("docsStaging"); ul.innerHTML = ""; ul.appendChild(li);
}});
async function salvar() {{
  const fd = new FormData();
  fd.append("processo", "{processo}");
  fd.append("tipo", document.getElementById("{pd}:eFileTipoCombo_valor").value);
  fd.append("token", tokenStaging || "");
  PF.ocupado(true);
  const r = await fetch("/ged/salvar", {{method: "POST", body: fd}});
  const j = await r.json(); PF.ocupado(false);
  if (!j.ok) {{ const e = document.getElementById("erroGed"); e.textContent = j.erro; e.hidden = false; return; }}
  PF.fecharEsteDialogo({{tipo: "recarregar-anexos"}});
}}
</script>"""
        return pagina("Novo Arquivo", corpo, s, dialogo=True, scripts=scripts)

    @r.post("/ged/staging")
    async def ged_staging(request: Request):
        if sessao(request) is None:
            return JSONResponse({"erro": "sessão expirada"}, status_code=401)
        f = await request.form()
        arq = f.get("arquivo")
        conteudo = await arq.read()
        token = secrets.token_hex(8)
        estado.staging[token] = {"nome": arq.filename, "tamanho": len(conteudo)}
        return {"token": token, "nome": arq.filename, "tamanho": f"{max(1, len(conteudo) // 1024)} KB"}

    @r.post("/ged/salvar")
    async def ged_salvar(request: Request):
        if sessao(request) is None:
            return JSONResponse({"ok": False, "erro": "sessão expirada"}, status_code=401)
        f = await request.form()
        tipo, token = f.get("tipo") or "", f.get("token") or ""
        pid = int(f.get("processo") or 0)
        if pid not in estado.processos:
            return {"ok": False, "erro": "Processo inválido."}
        if not tipo:
            return {"ok": False, "erro": "[Tipo de Documento] obrigatório!"}
        if token not in estado.staging:
            return {"ok": False, "erro": "[Arquivo] obrigatório!"}
        st = estado.staging.pop(token)
        a = estado.novo_anexo(pid, st["nome"], TIPOS_GED.get(tipo, ""), st["tamanho"])
        return {"ok": True, "id": a["id"]}

    # ------------------------------------------------------------------- conclusão de tarefa
    def form_confirmacao(t: dict, v: dict | None = None) -> str:
        """Form 'Confirmar agendamento'. `v` = valores já preenchidos (re-render após erro)."""
        v = v or {}
        pc = P["confirm"]
        p = estado.processos[t["processo_id"]]
        anexos_ids = [int(x) for x in (v.get("anexos") or "").split(",") if x.strip().isdigit()]
        anexos = [a for a in p["anexos"] if a["id"] in anexos_ids]
        linhas_upload = "".join(f'<tr data-ri="{n}"><td>{a["id"]}</td><td>{esc(a["nome"])}</td><td>{esc(a["tipo"])}</td>'
                                f'<td>{esc(a["tamanho"])}</td><td>{br(a["data"])}</td></tr>' for n, a in enumerate(anexos))
        cabecalho = (f'<div class="cartao"><div class="grade"><div><b>Processo</b>{esc(p["numero"])}</div>'
                     f'<div><b>Tarefa</b>{t["id"]} · {esc(estado.subtipo(t))}</div>'
                     f'<div><b>Prazo</b>{br(t["prazo"])}</div><div><b>Responsável</b>{esc(t["responsavel"])}</div></div></div>')
        thead = '<thead><tr><th>ID</th><th>Nome</th><th>Tipo de Documento</th><th>Tamanho</th><th>Data</th></tr></thead>'
        if t["tipo"] == TIPO_AUDIENCIA:
            campos = (
                f'<div class="campo"><label>Data da audiência inicial</label><input value="{br(t["registrado"])}" readonly></div>'
                f'<div class="campo"><label>Audiência inicial foi realizada na data informada em sistema? (*)</label>'
                f'{combo(f"{pc}:{estado.jid_aleatorio()}:CombosCombo", [("", "Selecione"), ("N", "Não"), ("S", "Sim")], v.get("realizada", ""), "realizada")}</div>'
                f'<div class="campo" id="blocoSim" hidden><label>Resultado da audiência (*)</label>'
                f'{combo(f"{pc}:{estado.jid_aleatorio()}", [("", "Selecione"), ("frutifera", "Frutífera"), ("infrutifera", "Infrutífera")], v.get("resultado_sim", ""), "resultado_sim")}</div>'
                f'<div class="campo" id="blocoNao" hidden><label>Resultado da audiência (*)</label>'
                f'{combo(f"{pc}:{estado.jid_aleatorio()}", [("", "Selecione"), ("redesignada", "Audiência redesignada"), ("ausencia", "Ausencia do autor"), ("conciliacao", "Conciliação")], v.get("resultado_nao", ""), "resultado_nao")}</div>'
                f'<h3>Anexar ata</h3><div class="filtros"><div class="campo"><label>Tipo de Documento</label>'
                f'{combo(f"{pc}:eFileTipoCombo", [("", "Selecione")] + list(TIPOS_ATA.items()), v.get("tipo_ata", ""), "tipo_ata")}</div>'
                f'<div class="campo"><label class="btn sec">+ Selecionar <input type="file" class="upload-tarefa" '
                f'id="{pc}:gedEFileAgendamentoDataTable:uploadEFile_input" accept=".pdf" hidden></label></div></div>'
                f'<table class="ui-datatable">{thead}<tbody id="{pc}:gedEFileAgendamentoDataTable_data">{linhas_upload}</tbody></table>')
            js_tipo = f'"{pc}:eFileTipoCombo_valor"'
            js_mostrar = ('const v = ev.detail.valor; document.getElementById("blocoSim").hidden = v !== "S"; '
                          'document.getElementById("blocoNao").hidden = v !== "N";')
            js_inicial = f'{{valor: {repr(v.get("realizada", ""))}}}'
        else:
            campos = (
                f'<div class="campo"><label>Anexar defesa? (*)</label>'
                f'{combo(f"{pc}:{estado.jid_aleatorio()}:CombosCombo", [("", "Selecione"), ("N", "Não"), ("S", "Sim")], v.get("anexar", ""), "anexar")}</div>'
                f'<div class="campo" id="blocoNao" hidden><label>Justificativa não anexação defesa (*)</label>'
                f'{combo(f"{pc}:{estado.jid_aleatorio()}", [("", "Selecione")] + [(j, j) for j in JUSTIFICATIVAS], v.get("justificativa", ""), "justificativa")}</div>'
                f'<div id="blocoSim" hidden><div class="filtros"><div class="campo"><label>Tipo de Documento (*)</label>'
                f'{combo(f"{pc}:gedEFileDataTable:comboEFileTipo", [("", "Selecione")] + list(TIPOS_DOC_CONCLUSAO.items()), v.get("tipo_doc", ""), "tipo_doc")}</div>'
                f'<div class="campo"><label class="btn sec">+ Selecionar <input type="file" class="upload-tarefa" '
                f'id="{pc}:gedEFileDataTable:uploadEFile_input" accept=".pdf" hidden></label></div></div>'
                f'<h3>Documentos</h3><table class="ui-datatable">{thead}<tbody id="{pc}:gedEFileDataTable_data">{linhas_upload}</tbody></table></div>')
            js_tipo = f'"{pc}:gedEFileDataTable:comboEFileTipo_valor"'
            js_mostrar = ('const v = ev.detail.valor; document.getElementById("blocoSim").hidden = v !== "S"; '
                          'document.getElementById("blocoNao").hidden = v !== "N";')
            js_inicial = f'{{valor: {repr(v.get("anexar", ""))}}}'
        corpo = (f'<h1>Confirmar agendamento</h1>{cabecalho}<div class="cartao">'
                 f'<form method="post" id="{pc}:formConfirm" action="/agendamentoContenciosoConfirm.elaw?id={t["id"]}">'
                 f'{campos}<input type="hidden" name="anexos" id="{pc}:anexosIds" value="{esc(v.get("anexos", ""))}">'
                 f'<div class="barra-botoes" style="margin-top:18px">'
                 f'<a class="btn sec" id="btnVoltar" href="/processoView.elaw?id={p["id"]}">Voltar</a>'
                 f'<a class="btn sec" id="btnConfirmaNao" href="/processoView.elaw?id={p["id"]}">Cancelar</a>'
                 f'<button class="btn ok" id="btnConfirmaSim" type="submit" name="acao" value="confirmar">Confirmar</button>'
                 f'</div></form></div>')
        scripts = f"""<script>
document.addEventListener("DOMContentLoaded", () => {{
  const combo = document.querySelector('[id$=":CombosCombo"]');
  const mostrar = (ev) => {{ {js_mostrar} }};
  combo.addEventListener("pf:change", mostrar);
  mostrar({{detail: {js_inicial}}});
  const oculto = document.getElementById("{pc}:anexosIds");
  document.querySelectorAll("input.upload-tarefa").forEach((inp) => {{
    const corpo = document.querySelector('tbody[id$="DataTable_data"]');
    inp.addEventListener("change", async () => {{
      for (const f of inp.files) {{
        const fd = new FormData(); fd.append("arquivo", f);
        fd.append("tipo", document.getElementById({js_tipo}).value);
        PF.ocupado(true);
        // o upload grava no GED AGORA, antes do Confirmar (igual ao sistema real)
        const r = await fetch("/ged/upload-tarefa?tarefa={t["id"]}", {{method: "POST", body: fd}});
        const j = await r.json(); PF.ocupado(false);
        if (!r.ok) {{ alert(j.erro || "falha no upload"); continue; }}
        const n = corpo.querySelectorAll("tr").length;
        const tr = document.createElement("tr"); tr.dataset.ri = n;
        for (const c of [j.id, j.nome, j.tipo, j.tamanho, j.data]) {{
          const td = document.createElement("td"); td.textContent = c; tr.appendChild(td); }}
        corpo.appendChild(tr);
        oculto.value = (oculto.value ? oculto.value + "," : "") + j.id;
      }}
      inp.value = "";
    }});
  }});
}});
</script>"""
        return corpo, scripts

    @r.get("/agendamentoContenciosoConfirm.elaw")
    async def confirm_get(request: Request, id: int = 0):
        if (s := sessao(request)) is None:
            return ir_login()
        t = estado.tarefas.get(id)
        if t is None:
            flash(s, "Tarefa não encontrada.", True)
            return voltar("/processoList.elaw")
        if t["situacao"] != "aberta":
            flash(s, "Esta tarefa já foi confirmada.", True)
            return voltar(f"/processoView.elaw?id={t['processo_id']}")
        corpo, scripts = form_confirmacao(t)
        return pagina("Confirmar agendamento", corpo, s, scripts=scripts)

    @r.post("/ged/upload-tarefa")
    async def upload_tarefa(request: Request, tarefa: int = 0):
        if sessao(request) is None:
            return JSONResponse({"erro": "sessão expirada"}, status_code=401)
        t = estado.tarefas.get(tarefa)
        if t is None or t["situacao"] != "aberta":
            return JSONResponse({"erro": "tarefa indisponível"}, status_code=400)
        f = await request.form()
        arq = f.get("arquivo")
        conteudo = await arq.read()
        tipo = f.get("tipo") or ""
        rotulo = {**TIPOS_DOC_CONCLUSAO, **TIPOS_ATA}.get(tipo, "")
        await asyncio.sleep(0.8)
        a = estado.novo_anexo(t["processo_id"], arq.filename, rotulo, len(conteudo))   # sem vínculo (ainda)
        return {"id": a["id"], "nome": a["nome"], "tipo": a["tipo"], "tamanho": a["tamanho"], "data": br(a["data"])}

    @r.post("/agendamentoContenciosoConfirm.elaw")
    async def confirm_post(request: Request, id: int = 0):
        if (s := sessao(request)) is None:
            return ir_login()
        t = estado.tarefas.get(id)
        if t is None:
            return voltar("/processoList.elaw")
        if t["situacao"] != "aberta":
            flash(s, "Esta tarefa já foi confirmada por outro usuário.", True)
            return voltar(f"/processoView.elaw?id={t['processo_id']}")
        f = await request.form()
        v = {k: f.get(k) or "" for k in ("anexar", "justificativa", "tipo_doc", "realizada", "resultado_sim",
                                         "resultado_nao", "tipo_ata", "anexos")}
        anexos_ids = [int(x) for x in v["anexos"].split(",") if x.strip().isdigit()]
        erros: list[str] = []
        if t["tipo"] == TIPO_AUDIENCIA:
            if v["realizada"] not in ("S", "N"):
                erros.append("[Audiência realizada?] obrigatório!")
            elif not v["resultado_sim" if v["realizada"] == "S" else "resultado_nao"]:
                erros.append("[Resultado da audiência] obrigatório!")
            if anexos_ids and not v["tipo_ata"]:
                erros.append("[Tipo de Documento] obrigatório!")
            tipo_label = TIPOS_ATA.get(v["tipo_ata"], "")
            rotulos = {"frutifera": "Frutífera", "infrutifera": "Infrutífera", "redesignada": "Audiência redesignada",
                       "ausencia": "Ausencia do autor", "conciliacao": "Conciliação"}
            detalhe = (f"Realizada: {'Sim' if v['realizada'] == 'S' else 'Não'}; resultado: "
                       f"{rotulos.get(v['resultado_sim'] or v['resultado_nao'], '')}")
        else:
            if v["anexar"] not in ("S", "N"):
                erros.append("[Anexar defesa?] obrigatório!")
            elif v["anexar"] == "N" and not v["justificativa"]:
                erros.append("[Justificativa não anexação defesa] obrigatório!")
            elif v["anexar"] == "S":
                if not anexos_ids:
                    erros.append("[Documento] obrigatório!")
                if not v["tipo_doc"]:
                    erros.append("[Tipo de Documento] obrigatório!")
            tipo_label = TIPOS_DOC_CONCLUSAO.get(v["tipo_doc"], "")
            detalhe = ("Anexar defesa: Sim" if v["anexar"] == "S"
                       else f"Anexar defesa: Não; justificativa: {v['justificativa']}")
        if not erros and t["falhar_confirmacao"]:
            erros.append("Erro inesperado ao confirmar (falha simulada pelo mock). Tente novamente.")
        if erros:   # fica no form (o que já subiu continua no GED, sem vínculo = órfão)
            for e in erros:
                flash(s, e, True)
            corpo, scripts = form_confirmacao(t, v)
            return pagina("Confirmar agendamento", corpo, s, scripts=scripts)
        if anexos_ids:
            await asyncio.sleep(2.5)   # com anexo, o sistema real leva alguns segundos para sair do form
        p = estado.processos[t["processo_id"]]
        for a in p["anexos"]:
            if a["id"] in anexos_ids:
                a["tarefa_id"] = t["id"]
                a["tipo"] = a["tipo"] or tipo_label
        estado.concluir_tarefa(t, estado.usuario["login"], detalhe)
        if t["tipo"] == TIPO_CONTESTACAO and v["anexar"] == "N" and v["justificativa"] == "Prazo de contestação em curso":
            nova = estado._nova_tarefa(p["id"], TIPO_CONTESTACAO, estado.hoje, 20, responsavel=t["responsavel"],
                                       descricao="Tarefa reaberta: prazo de contestação em curso.", anterior=t["id"])
            flash(s, f"Nova tarefa {nova['id']} criada (prazo de contestação em curso).")
        flash(s, "Agendamento confirmado com sucesso.")
        return voltar(f"/processoView.elaw?id={p['id']}")

    # ------------------------------------------------------------------- pesquisa de tarefas
    def pesquisar_tarefas(fl: dict) -> list[int]:
        ini, fim = _data_br(fl["inicio"]), _data_br(fl["fim"])
        campo = {"data": "prazo", "dataRegistrado": "registrado", "dataConfirmado": "confirmado_em"}[fl["tipo_data"]]
        achadas = []
        for t in estado.tarefas.values():
            d = t[campo]
            if d is None or not (ini <= d <= fim):
                continue
            if estado.status_tarefa(t) not in fl["status"]:
                continue
            if fl["tipos"] and t["tipo"] not in fl["tipos"]:
                continue
            txt = fl["texto"].strip()
            p = estado.processos[t["processo_id"]]
            if txt:
                if fl["tipo_pesquisa"] == "id" and txt != str(t["id"]):
                    continue
                if fl["tipo_pesquisa"] == "processo_id" and txt != str(p["id"]):
                    continue
                if fl["tipo_pesquisa"] == "numero" and _so_digitos(txt) != _so_digitos(p["numero"]):
                    continue
                if fl["tipo_pesquisa"] == "geral" and txt.casefold() not in (p["numero"] + p["parte_contraria"]).casefold():
                    continue
            achadas.append(t["id"])
        return sorted(achadas)

    @r.get("/agendamentoContenciosoList.elaw")
    async def tarefas_list(request: Request):
        if (s := sessao(request)) is None:
            return ir_login()
        fl, pt = s["tarefas"], P["tarefas"]
        form_id = f"{pt}:formPesquisa"
        linhas, rodape = "", ""
        if fl["resultado"] is not None:
            for n, tid in enumerate(fl["resultado"][:50]):
                t = estado.tarefas[tid]
                p = estado.processos[t["processo_id"]]
                linhas += (f'<tr data-ri="{n}"><td>{icone_status(estado.status_tarefa(t))}</td><td><input type="checkbox"></td>'
                           f'<td>{t["id"]}</td><td>{br(t["prazo"])}</td><td>{br(t["registrado"])}</td><td>ALERTA</td>'
                           f'<td>{esc(estado.subtipo(t))}</td><td>{esc(p["parte_contraria"])}</td><td>{esc(p["numero"])}</td></tr>')
            if not fl["resultado"]:
                linhas = '<tr class="ui-datatable-empty-message"><td colspan="9">Nenhum registro encontrado.</td></tr>'
            rodape = f'<div class="ui-paginator-current">{len(fl["resultado"])} registro(s) encontrado(s)</div>'
        tipos_pesq = [("geral", "Geral"), ("id", "ID"), ("processo_id", "Processo ID"), ("numero", "Número do Processo")]
        tipos_data = [("data", "Agendamento"), ("dataRegistrado", "Cadastro"), ("dataConfirmado", "Confirmado")]
        corpo = (
            f'<h1>Tarefas</h1><div class="cartao"><form method="post" id="{form_id}">'
            f'<div class="filtros">'
            f'<div class="campo"><label>Tipo de pesquisa</label>{combo(f"{pt}:comboTipoPesquisa", tipos_pesq, fl["tipo_pesquisa"], "tipo_pesquisa")}</div>'
            f'<div class="campo"><label>Texto</label><input id="{pt}:txtSearch" name="texto" value="{esc(fl["texto"])}"></div>'
            f'<div class="campo"><label>Status (*)</label>{checkmenu(f"{pt}:status", f"{pt}:status", list(STATUS_FILTRO.items()), fl["status"], form_id)}</div>'
            f'<div class="campo"><label>Tipo de Tarefa</label>{checkmenu(f"{pt}:selectManyAgendamentoTipo", f"{pt}:selectManyAgendamentoTipo", list(estado.tipos_tarefa.items()), fl["tipos"], form_id)}</div>'
            f'</div><div class="filtros">'
            f'<div class="campo"><label>Data</label>{combo(f"{pt}:comboDataTipo", tipos_data, fl["tipo_data"], "tipo_data")}</div>'
            f'<div class="campo"><label>De (*)</label><input class="ui-calendar" id="{pt}:idDoCalendarStart_input" value="{esc(fl["inicio"])}" autocomplete="off">'
            f'<input type="hidden" id="{pt}:idDoCalendarStart" name="inicio" value="{esc(fl["inicio"])}"></div>'
            f'<div class="campo"><label>Até (*)</label><input class="ui-calendar" id="{pt}:idDoCalendarEnd_input" value="{esc(fl["fim"])}" autocomplete="off">'
            f'<input type="hidden" id="{pt}:idDoCalendarEnd" name="fim" value="{esc(fl["fim"])}"></div>'
            f'</div><div class="barra-botoes">'
            f'<button class="btn" id="{pt}:btnPesquisar" name="acao" value="pesquisar">Pesquisar</button>'
            f'<button class="btn sec" id="{pt}:btnLimparPesquisa" name="acao" value="limpar">Limpar Pesquisa</button>'
            f'<button class="btn sec" id="{pt}:btnExcel" type="button" onclick="PF.abrirDialogo(\'/dialogs/elawReport/'
            f'elawReportGerarDialog.elaw?origem=tarefas\',\'Gerar Relatório\',640)">Excel</button></div></form></div>'
            f'<div class="cartao"><table class="ui-datatable" id="{pt}:dtAgendamentoContenciosoResults"><thead><tr>'
            f'<th>Status</th><th></th><th>Tarefa ID</th><th>Prazo</th><th>Cadastro</th><th>Tipo</th><th>Sub Tipo</th>'
            f'<th>Parte Contrária</th><th>Número do Processo</th></tr></thead>'
            f'<tbody id="{pt}:dtAgendamentoContenciosoResults_data">{linhas}</tbody></table>{rodape}</div>')
        return pagina("Tarefas", corpo, s)

    @r.post("/agendamentoContenciosoList.elaw")
    async def tarefas_post(request: Request):
        if (s := sessao(request)) is None:
            return ir_login()
        f = await request.form()
        pt = P["tarefas"]
        if f.get("acao") == "limpar":
            s["tarefas"] = estado.filtros_tarefas_limpos(estado.hoje)
            return voltar("/agendamentoContenciosoList.elaw")
        novo = {"tipo_pesquisa": f.get("tipo_pesquisa") or "geral", "texto": f.get("texto") or "",
                "tipo_data": f.get("tipo_data") or "data", "status": f.getlist(f"{pt}:status"),
                "tipos": f.getlist(f"{pt}:selectManyAgendamentoTipo"),
                "inicio": f.get("inicio") or "", "fim": f.get("fim") or "",
                "resultado": s["tarefas"]["resultado"]}   # pesquisa inválida MANTÉM o resultado anterior
        erro = None
        if not novo["status"]:
            erro = "Favor definir um status!"
        elif "8" in novo["status"]:
            erro = "Para pesquisar 'A Vencer' selecione uma única Área do direito."
        elif not (_data_br(novo["inicio"]) and _data_br(novo["fim"])):
            erro = "Período inválido: informe as datas no formato dd/mm/aaaa."
        if novo["tipo_data"] not in ("data", "dataRegistrado", "dataConfirmado"):
            novo["tipo_data"] = "data"
        if erro:
            flash(s, erro, True)
        else:
            novo["resultado"] = pesquisar_tarefas(novo)
        s["tarefas"] = novo
        return voltar("/agendamentoContenciosoList.elaw")

    # ------------------------------------------------------------------- modal "Gerar Relatório"
    @r.get("/dialogs/elawReport/elawReportGerarDialog.elaw")
    async def rel_passo1(request: Request, origem: str = "tarefas", msg: str = ""):
        if (s := sessao(request)) is None:
            return ir_login()
        pr = P["rel"]
        aviso = f'<p class="aviso">{esc(msg)}</p>' if msg else ""
        opcoes = "".join(f'<label class="opcao"><input type="radio" name="opcao" value="{v}"> {esc(l)}</label>'
                         for v, l in (("preconfig", "Modelos Pré-Configurado"), ("montar", "Montar um relatório"),
                                      ("meus", "Meus modelos de relatório")))
        corpo = (f'<form method="post" id="{pr}:elawReportForm" action="/dialogs/elawReport/elawReportGerarDialog.elaw">'
                 f'<h2>Qual opção de relatório você deseja?</h2>{aviso}{opcoes}<input type="hidden" name="origem" value="{esc(origem)}">'
                 f'<div class="barra-botoes"><button type="button" class="btn sec" id="{pr}:elawReportForm:fecharBtn" '
                 f'onclick="PF.fecharEsteDialogo()">Fechar</button>'
                 f'<button class="btn" id="{pr}:elawReportForm:continuarBtn" name="passo" value="2">Continuar</button></div></form>')
        return pagina("Gerar Relatório", corpo, s, dialogo=True)

    @r.post("/dialogs/elawReport/elawReportGerarDialog.elaw")
    async def rel_post(request: Request):
        if (s := sessao(request)) is None:
            return ir_login()
        f = await request.form()
        pr = P["rel"]
        if f.get("passo") == "2":
            if f.get("opcao") != "preconfig":
                return voltar("/dialogs/elawReport/elawReportGerarDialog.elaw?msg="
                              + ("Escolha uma opção." if not f.get("opcao") else
                                 "Neste mock só a opção 'Modelos Pré-Configurado' está disponível."))
            corpo = (f'<form method="post" id="{pr}:elawReportForm">'
                     f'<h2>Modelos pré-configurados</h2><div class="campo"><label>Modelo</label>'
                     f'{combo(f"{pr}:elawReportForm:selectElawReport", [("", "Selecione")] + list(TEMPLATES.items()), "", "template")}</div>'
                     f'<div class="barra-botoes"><button type="button" class="btn sec" id="{pr}:elawReportForm:elawReportCopyBtn">Copiar e Criar Novo</button>'
                     f'<button class="btn" id="{pr}:elawReportForm:elawReportGerarBtn" name="passo" value="3" disabled>Gerar Relatório</button></div></form>')
            scripts = (f'<script>document.addEventListener("DOMContentLoaded",()=>{{'
                       f'document.getElementById("{pr}:elawReportForm:selectElawReport").addEventListener("pf:change",(ev)=>{{'
                       f'document.getElementById("{pr}:elawReportForm:elawReportGerarBtn").disabled = !ev.detail.valor;}});}});</script>')
            return pagina("Gerar Relatório", corpo, s, dialogo=True, scripts=scripts)
        # passo 3: gera (assíncrono) e mostra o ID da solicitação
        template = f.get("template") or ""
        ids = s["tarefas"]["resultado"] or []
        if not template:
            return voltar("/dialogs/elawReport/elawReportGerarDialog.elaw?msg=Escolha um modelo.")
        if not ids:
            corpo = '<p class="aviso">Nenhum registro na pesquisa atual: nada foi gerado.</p>'
            return pagina("Gerar Relatório", corpo, s, dialogo=True)
        fl = s["tarefas"]
        rel = estado.gerar_relatorio_tarefas(
            ids, template, f"Status {','.join(fl['status'])}; tipos {','.join(fl['tipos']) or 'todos'}; "
                           f"{fl['tipo_data']} de {fl['inicio']} a {fl['fim']}")
        corpo = (f'<div class="sucesso"><b>Sua solicitação foi enviada com sucesso!</b><br>Quando ficar pronta, ela aparece '
                 f'em Meus Relatórios (ícone da maleta). Solicitação ID {rel["id"]}.</div>'
                 f'<div class="barra-botoes"><button type="button" class="btn" id="{pr}:elawReportForm:elawReportFecharBtn" '
                 f'onclick="PF.fecharEsteDialogo()">Fechar</button></div>')
        return pagina("Gerar Relatório", corpo, s, dialogo=True)

    # ------------------------------------------------------------------- "Meus Relatórios"
    @r.get("/userElawReportRequestList.elaw")
    async def meus_relatorios(request: Request, etoken: str = ""):
        if (s := sessao(request)) is None:
            return ir_login()
        if etoken != s["etoken"]:   # só se chega pelo painel da maleta (URL direta = acesso negado)
            return pagina("Acesso Negado", '<h1>Acesso Negado</h1><p>Abra "Meus Relatórios" pelo ícone da maleta.</p>',
                          s, status=403)
        m, pm = s["meus"], P["meus"]
        if request.query_params.get("r") != "1":
            m["visivel"] = False    # a lista abre VAZIA: só carrega depois de "Pesquisar"
        linhas = ""
        if m["visivel"]:
            dia = _data_br(m["data"])
            rels = [x for x in estado.relatorios.values() if x["usuario"] == s["usuario"]
                    and (dia is None or x["criado"].date() == dia)]
            for x in sorted(rels, key=lambda x: x["id"], reverse=True):
                pronto = estado.relatorio_pronto(x)
                if m["status"] == "3" and not pronto:
                    continue
                status = ('<img src="/static/icones/checkbox_green.png" title="Processado">' if pronto
                          else '<img src="/static/icones/checkbox_yellow.png" title="Executando">')
                clipe = (f'<a href="/relatorios/{x["id"]}/download" data-ajax="false" title="Arquivo pronto para download">'
                         f'<img src="/static/icones/clip.png" alt="baixar"></a>' if pronto else "")
                linhas += (f'<tr><td>{x["id"]}</td><td>{"Não" if pronto else "Sim"}</td><td>{esc(x["nome"])}</td>'
                           f'<td>{br(x["criado"])}</td><td>{br(x["criado"]) if pronto else ""}</td><td>XLSX</td>'
                           f'<td>{status}</td><td>{clipe}</td></tr>')
            if not linhas:
                linhas = '<tr class="ui-datatable-empty-message"><td colspan="8">Nenhum registro encontrado.</td></tr>'
        acao = f"/userElawReportRequestList.elaw?etoken={s['etoken']}"
        status_op = [("", "Todos"), ("3", "Processado")]
        corpo = (f'<h1>Meus Relatórios</h1><div class="cartao"><form method="post" action="{acao}" class="filtros">'
                 f'<div class="campo"><label>Data</label><input id="{pm}:dataFiltro" name="data" value="{esc(m["data"])}"></div>'
                 f'<div class="campo"><label>Status</label>{combo(f"{pm}:statusCombo", status_op, m["status"], "status")}</div>'
                 f'<div class="barra-botoes"><button class="btn" id="{pm}:btnPesquisar" name="acao" value="pesquisar">Pesquisar</button>'
                 f'<button class="btn sec" id="{pm}:btnLimparPesquisa" name="acao" value="limpar">Limpar Pesquisa</button></div>'
                 f'</form></div><div class="cartao"><table class="ui-datatable" id="{pm}:dtRelatorios"><thead><tr><th>ID</th>'
                 f'<th>Em Fila</th><th>Nome Relatório</th><th>Data Registrado</th><th>Data Enviado</th><th>Tipo</th>'
                 f'<th>Status</th><th></th></tr></thead><tbody id="{pm}:dtRelatorios_data">{linhas}</tbody></table></div>')
        return pagina("Meus Relatórios", corpo, s)

    @r.post("/userElawReportRequestList.elaw")
    async def meus_relatorios_post(request: Request, etoken: str = ""):
        if (s := sessao(request)) is None:
            return ir_login()
        if etoken != s["etoken"]:
            return pagina("Acesso Negado", "<h1>Acesso Negado</h1>", s, status=403)
        f = await request.form()
        if f.get("acao") == "limpar":
            s["meus"] = {"data": br(estado.hoje), "status": "", "visivel": False}
            return voltar(f"/userElawReportRequestList.elaw?etoken={etoken}")
        s["meus"] = {"data": f.get("data") or "", "status": f.get("status") or "", "visivel": True}
        return voltar(f"/userElawReportRequestList.elaw?etoken={etoken}&r=1")

    @r.get("/relatorios/{rid}/download")
    async def baixar_relatorio(rid: int, request: Request):
        if (s := sessao(request)) is None:
            return ir_login()
        rel = estado.relatorios.get(rid)
        if rel is None or rel["usuario"] != s["usuario"] or not estado.relatorio_pronto(rel):
            return HTMLResponse("Relatório indisponível.", status_code=404)
        from openpyxl import Workbook
        from openpyxl.styles import Font
        wb = Workbook()
        ws = wb.active
        ws.title = rel["nome"][:31]
        # cabeçalho do relatório NÃO fica na linha 1 (o parser do robô precisa achá-lo sozinho)
        ws.append([f"Relatório: {rel['nome']}"])
        ws.append([f"Gerado em: {br(rel['criado'])}"])
        ws.append([f"Usuário: {rel['usuario']}"])
        ws.append([f"Filtros: {rel['filtros'] or '-'}"])
        ws.append([])
        ws.append(["Processo - ID", "Número do Processo", "Tarefa - ID", "Tarefa - Status", "Tipo", "Sub Tipo",
                   "Data Registrado", "Data Agendamento", "Parte Contrária", "Responsável"])
        for c in ws[6]:
            c.font = Font(bold=True)
        for linha in rel["linhas"]:
            ws.append(linha)
        buf = io.BytesIO()
        wb.save(buf)
        nome = f"report_elawReport_99_{rid}{secrets.token_hex(3)}.xlsx"
        return Response(buf.getvalue(), headers={"Content-Disposition": f'attachment; filename="{nome}"'},
                        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ------------------------------------------------------------------- ganchos do mock
    @r.get("/__mock/cenarios")
    async def cenarios(request: Request):
        s = sessao(request)
        linhas = ""
        for p in sorted(estado.processos.values(), key=lambda p: p["cenario"]):
            tarefas = ", ".join(f'{t["id"]} ({STATUS_ROTULO[estado.status_tarefa(t)]})'
                                for t in estado.tarefas_do_processo(p["id"]))
            linhas += (f'<tr><td><span class="etiqueta">{esc(p["cenario"])}</span></td><td>{esc(p["numero"])}</td>'
                       f'<td>{esc(p["esperado"])}</td><td>{tarefas}</td></tr>')
        corpo = (f'<h1>Cenários do mock</h1><p>Cada processo fictício demonstra uma regra do robô. '
                 f'Grupo de trabalho do cliente no CPJ: <b>{estado.gt_cliente}</b>.</p>'
                 f'<div class="cartao"><table class="ui-datatable"><thead><tr><th>Cenário</th><th>Processo</th>'
                 f'<th>Resultado esperado</th><th>Tarefas (agora)</th></tr></thead><tbody>{linhas}</tbody></table></div>')
        return pagina("Cenários", corpo, s)

    @r.post("/__mock/expirar-sessoes")
    async def expirar():
        n = len(estado.sessoes)
        estado.sessoes.clear()
        return {"sessoes_encerradas": n}

    return r
