"""
Orquestrador da rodada (filas "Anexar contestação" e "Confirmar audiência").

  1. relatório de tarefas do eLaw (gera e baixa — ou reaproveita o de hoje, ou usa --xlsx)
     ou, na consulta de UM processo, as tarefas em aberto lidas direto na ficha;
  2. lê o xlsx -> tarefas pendentes das duas filas;
  3. consulta o CPJ (só leitura) e aplica as regras (regras.py) -> PLANO;
  4. DRY-RUN (padrão): só grava o plano.  --executar: conclui as prontas no eLaw;
  5. grava plano.csv / resultado.csv / auditoria.jsonl / log.txt / PRECISA DE VOCE.xlsx.

Segurança: dry-run por padrão; cada resultado incerto é re-checado no eLaw pelo ID da tarefa;
o lote ABORTA após N erros seguidos ou se a sessão do eLaw cair (o robô nunca tenta logar).
"""
from __future__ import annotations
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from . import regras as R
from . import saida
from .conexao import NaoAutenticado, esta_logado
from .tarefas_xlsx import Tarefa, ler_tarefas
from .texto import norm

FILA_CONTESTACAO, FILA_AUDIENCIA = "contestacao", "audiencia"


@dataclass
class Item:
    fila: str
    linha_xlsx: int
    numero: str
    id_tarefa: str
    assunto: str
    status_elaw: str
    data: str                   # data de REGISTRO da tarefa no eLaw (dd/mm/aaaa)
    situacao: str = ""
    acao: str = ""
    detalhe: str = ""
    pdf: str = ""               # nome do PDF (no plano) / caminho local (depois de baixar)
    cpj_doc: str = ""           # id do documento no CPJ (baixado só na execução)
    resultado: str = ""         # audiência: Frutífera | Infrutífera
    anexo: str = ""             # ID do arquivo no GED do eLaw (enviado agora ou já existente)
    antes: str = ""             # reagendamento: a situação que levou a reagendar


# ---------------------------------------------------------------- plano
def _fila(t: Tarefa, cfg: dict) -> str | None:
    alvo = norm(t.assunto) if t.assunto else norm(t.texto)
    if norm(cfg["tarefa"]["assunto"]) in alvo:
        return FILA_CONTESTACAO
    if cfg.get("audiencia", {}).get("ativo") and norm(cfg["audiencia"]["assunto"]) in alvo:
        return FILA_AUDIENCIA
    return None


def montar_plano(tarefas: list[Tarefa], cfg: dict, numero: str | None = None) -> tuple[list[Item], dict]:
    ignorar = [norm(s) for s in cfg["tarefa"].get("status_ignorar", [])]
    cont = {"linhas": len(tarefas), "outro_assunto": 0, "nao_pendentes": 0}
    itens: list[Item] = []
    vistos: set[tuple[str, str]] = set()
    for t in tarefas:
        fila = _fila(t, cfg)
        if fila is None:
            cont["outro_assunto"] += 1
            continue
        if t.status and any(s in norm(t.status) for s in ignorar):
            cont["nao_pendentes"] += 1
            continue
        if numero and re.sub(r"\D", "", t.numero or "") != re.sub(r"\D", "", numero):
            continue
        it = Item(fila, t.linha, t.numero or "", t.id_tarefa or "", t.assunto, t.status, t.data)
        chave = (it.numero, it.id_tarefa)
        if not t.numero:
            it.situacao, it.detalhe = R.SEM_NUMERO, "nº do processo não encontrado na linha do relatório"
        elif chave in vistos:
            it.situacao, it.detalhe = R.DUPLICADA, "a mesma tarefa já está no lote"
        vistos.add(chave)
        itens.append(it)
    return itens, cont


def _data_iso(data_br: str) -> str:
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", data_br or "")
    return f"{m[3]}-{m[2]}-{m[1]}" if m else ""


def avaliar_no_cpj(itens: list[Item], cli, cfg: dict, log: Callable, audit: Callable,
                   hoje: date | None = None) -> None:
    """Classifica cada tarefa consultando o CPJ (só leitura) e aplicando as regras puras."""
    from .cpj import CPJIndisponivel
    eventos = R.EventosCPJ(cfg["cpj"].get("evento_pauta", "Pauta - Contestação"),
                           cfg["cpj"].get("evento_anexada", "Anexar contestação no eLaw"))
    apos = int(cfg["tarefa"].get("reagendar_apos_dias", 17))
    alvo = [it for it in itens if not it.situacao]
    log(f"Consultando o CPJ para {len(alvo)} tarefa(s)...")
    falhas = 0
    for n, it in enumerate(alvo, 1):
        try:
            pj = cli.localizar(it.numero)
            tram = cli.tramitacoes(pj) if pj else []
            if it.fila == FILA_CONTESTACAO:
                av = R.avaliar_contestacao(pj, tram, lambda: cli.documentos(pj), it.numero, eventos)
                av = R.aplicar_reagendamento(av, it.data, apos, hoje)
            else:
                av = R.avaliar_audiencia(pj, tram, cli.documentos_da_tarefa, lambda: cli.documentos(pj),
                                         _data_iso(it.data))
        except CPJIndisponivel as e:
            it.situacao, it.detalhe = R.CPJ_SEM_RESPOSTA, str(e)
            falhas += 1
            if falhas >= 5 and falhas > n // 2:   # a API caiu de vez: não adianta seguir
                raise
            continue
        it.situacao, it.acao, it.detalhe, it.antes, it.resultado = (av.situacao, av.acao, av.detalhe,
                                                                     av.antes, av.resultado)
        if av.doc:
            it.pdf, it.cpj_doc = R.nome_doc(av.doc), str(av.doc["id_ged"])
    audit("cpj", consultadas=len(alvo), sem_resposta=falhas, requisicoes=getattr(cli, "requisicoes", None))
    if falhas:
        log(f"  [aviso] o CPJ não respondeu para {falhas} tarefa(s); ficam para a próxima rodada.")


# ---------------------------------------------------------------- execução de UMA tarefa
class Execucao:
    """Executa as tarefas prontas na sessão do eLaw. Nenhum método levanta exceção, exceto
    NaoAutenticado (sessão caiu): essa sobe para o lote abortar com o código certo."""

    def __init__(self, page, cfg: dict, cli, pasta: Path, log: Callable):
        self.page, self.cfg, self.cli, self.pasta, self.log = page, cfg, cli, pasta, log
        rc = cfg["relatorio"]
        hoje = date.today()
        self.periodo = (hoje - timedelta(days=rc["dias_antes"]), hoje + timedelta(days=rc.get("dias_depois", 0)),
                        rc.get("tipo_data", "dataRegistrado"))

    def rechecar(self, it: Item) -> str:
        """Status REAL da tarefa no eLaw ('concluida' | 'pendente' | 'nao_encontrada' | 'falhou')."""
        from .fluxos import tarefas
        if not it.id_tarefa:
            return "sem_id"
        try:
            st = tarefas.status_da_tarefa(self.page, it.id_tarefa, *self.periodo)
        except NaoAutenticado:
            raise
        except Exception as e:
            self.log(f"  [!] re-checagem falhou: {type(e).__name__}: {e}")
            return "falhou"
        self.log(f"  re-checagem no eLaw: tarefa {it.id_tarefa} = {st}")
        return st

    def baixar_do_cpj(self, it: Item) -> Path | None:
        nome = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", it.pdf).strip(" .") or f"{it.cpj_doc}.pdf"
        try:
            return self.cli.baixar(it.cpj_doc, self.pasta / "pdfs" / nome)
        except Exception as e:
            it.situacao, it.detalhe = R.ERRO, f"não consegui baixar o PDF do CPJ ({type(e).__name__})"
            self.log(f"  [!] {it.detalhe}")
            return None

    def executar(self, it: Item) -> None:
        if it.fila == FILA_AUDIENCIA:
            self._audiencia(it)
        elif it.acao == R.CONCLUIR_JA_ANEXADA:
            self._sem_anexo(it, self.cfg["tarefa"]["justificativa_ja_anexada"], R.CONCLUIDA_JA_ANEXADA)
        elif it.acao == R.REAGENDAR:
            self._sem_anexo(it, self.cfg["tarefa"]["justificativa_reagendar"], R.REAGENDADA)
        else:
            self._anexar(it)

    def _falhou(self, it: Item, e: Exception, prefixo: str = "") -> None:
        """Erro inesperado: se houve upload, re-checa; se a tarefa segue pendente, aponta o ÓRFÃO."""
        from .fluxos.concluir import TarefaNaoEncontrada
        primeira_linha = (str(e).strip().splitlines() or [""])[0]   # sem o "call log" do Playwright
        erro = f"{prefixo}{type(e).__name__}: {primeira_linha}"
        id_anexo = getattr(e, "id_anexo", None)
        if isinstance(e, TarefaNaoEncontrada):   # a linha sumiu da ficha: alguém concluiu antes?
            if self.rechecar(it) == "concluida":
                it.situacao, it.detalhe = R.JA_CONCLUIDA, "a tarefa já estava concluída no eLaw (não pelo robô)"
                self.log(f"  {it.detalhe}")
                return
        elif id_anexo:
            it.anexo = id_anexo
            if self.rechecar(it) == "concluida":
                it.situacao, it.detalhe = R.CONCLUIDA, f"confirmado na re-checagem após erro: {erro}"
                return
            erro += f" | ANEXO ÓRFÃO no GED: {id_anexo} (excluir antes de re-tentar)"
        it.situacao, it.detalhe = R.ERRO, erro
        self.log(f"  [!] {it.detalhe}")

    def _resultado_incerto(self, it: Item, r: dict, situacao_ok: str, base: str) -> None:
        """Clicou Confirmar e continuou no form: só a re-checagem pelo ID diz a verdade."""
        if r["ok"]:
            it.situacao, it.detalhe = situacao_ok, base
            self.log(f"  {situacao_ok}. {base}")
            return
        if self.rechecar(it) == "concluida":
            it.situacao, it.detalhe = situacao_ok, f"{base} (confirmado na re-checagem: o form demorou a fechar)"
            return
        avisos = "; ".join(r.get("avisos") or []) or "sem aviso na tela"
        it.situacao = R.NAO_CONCLUIU
        it.detalhe = f"{base} | continuou no form ({avisos})" + (
            f" | ANEXO ÓRFÃO no GED: {it.anexo} (excluir antes de re-tentar)" if r.get("id_anexo") else "")
        self.log(f"  [!] {it.detalhe}")

    def _anexar(self, it: Item) -> None:
        from .fluxos import concluir
        pdf = self.baixar_do_cpj(it)
        if pdf is None:
            return
        it.pdf = str(pdf)
        tcfg = self.cfg["tarefa"]
        try:
            r = concluir.concluir_com_anexo(self.page, it.numero, tcfg["assunto"], pdf, tcfg["tipo_documento"],
                                            it.id_tarefa or None)
        except concluir.JaAnexado as e:
            it.anexo = ",".join(a["id"] for a in e.anexos)
            if tcfg.get("ja_anexado", "concluir") == "concluir":
                self.log(f"  {e} -> não reenvia; conclui como '{tcfg['justificativa_ja_anexada']}'")
                self._sem_anexo(it, tcfg["justificativa_ja_anexada"], R.CONCLUIDA_JA_ANEXADA, motivo=str(e))
            else:
                it.situacao, it.detalhe = R.JA_ANEXADO, f"{e} — NÃO reenviado; revisar"
                self.log(f"  [!] {it.detalhe}")
            return
        except NaoAutenticado:
            raise
        except Exception as e:
            self._falhou(it, e)
            return
        it.anexo = r.get("id_anexo") or ""
        self._resultado_incerto(it, r, R.CONCLUIDA, f"contestação anexada (GED {it.anexo})")

    def _sem_anexo(self, it: Item, justificativa: str, situacao_ok: str, motivo: str = "") -> None:
        from .fluxos import concluir
        base = f"{motivo or it.detalhe} -> 'Anexar defesa? = Não' + '{justificativa}'"
        try:
            r = concluir.concluir_sem_anexo(self.page, it.numero, self.cfg["tarefa"]["assunto"], justificativa,
                                            it.id_tarefa or None)
        except NaoAutenticado:
            raise
        except Exception as e:
            self._falhou(it, e, prefixo=f"{motivo} | " if motivo else "")
            return
        self._resultado_incerto(it, r, situacao_ok, base)

    def _audiencia(self, it: Item) -> None:
        from .fluxos import concluir
        acfg = self.cfg["audiencia"]
        tipo = acfg["tipo_ata_com_acordo"] if it.resultado == "Frutífera" else acfg["tipo_ata_sem_acordo"]
        ata = None
        if it.cpj_doc:
            ata = self.baixar_do_cpj(it)
            if ata is None:
                return
            it.pdf = str(ata)

        def tentar(arquivo):
            return concluir.concluir_audiencia(self.page, it.numero, acfg["assunto"], True, it.resultado,
                                               arquivo, tipo, it.id_tarefa or None)
        nota = ""
        try:
            try:
                r = tentar(ata)
            except concluir.JaAnexado as e:
                it.anexo = ",".join(a["id"] for a in e.anexos)
                nota = "ata já estava no processo (não reenviada)"
                self.log(f"  {nota}: {it.anexo}")
                r = tentar(None)
        except NaoAutenticado:
            raise
        except Exception as e:
            self._falhou(it, e)
            return
        if r.get("id_anexo"):
            it.anexo = r["id_anexo"]
        base = f"{it.resultado}; " + (f"ata anexada (GED {it.anexo})" if r.get("id_anexo") else nota or "sem ata")
        self._resultado_incerto(it, r, R.CONCLUIDA, base)


# ---------------------------------------------------------------- relatório da rodada
def _obter_relatorio(cfg: dict, sess, log: Callable, audit: Callable, novo: bool) -> Path | None:
    """Gera e baixa o relatório da rodada. Se já há um de HOJE, reaproveita (a execução re-checa cada
    tarefa no eLaw, então um relatório de horas atrás é seguro) — a não ser que peçam um novo."""
    from .fluxos import relatorio, tarefas
    rc, pasta = cfg["relatorio"], Path(cfg["pastas"]["relatorios"])
    hoje = date.today()
    prefixo = f"tarefas_{hoje:%Y-%m-%d}_rodada"
    do_dia = sorted(pasta.glob(f"{prefixo}_*.xlsx"), key=lambda p: p.stat().st_mtime)
    if do_dia and not novo:
        log(f"Reaproveitando o relatório de hoje: {do_dia[-1].name} (use --novo-relatorio para gerar outro).")
        audit("relatorio_reaproveitado", arquivo=str(do_dia[-1]))
        return do_dia[-1]
    tipos = list(rc["tipos"]) + ([cfg["audiencia"]["tipo_tarefa"]] if cfg.get("audiencia", {}).get("ativo") else [])
    inicio, fim = hoje - timedelta(days=rc["dias_antes"]), hoje + timedelta(days=rc.get("dias_depois", 0))
    log(f"Gerando o relatório de tarefas no eLaw (entrada de {inicio:%d/%m/%Y} a {fim:%d/%m/%Y})...")
    r = tarefas.gerar_relatorio(sess.page, pasta, rc["template_tarefas"], rc["status"], tipos, inicio, fim,
                                rc.get("tipo_data", "dataRegistrado"), rc.get("timeout_s", 180))
    audit("relatorio", **{k: v for k, v in r.items() if k != "itens"})
    if not r.get("ok"):
        raise relatorio.RelatorioIndisponivel(f"Relatório de tarefas: {r.get('motivo')}")
    if r.get("vazio"):
        return None
    r = relatorio.renomear(r, prefixo)
    log(f"  relatório {r.get('id_relatorio')} baixado ({r['bytes']} bytes).")
    return Path(r["arquivo"])


# ---------------------------------------------------------------- a rodada
def orquestrar(cfg: dict, conectar: Callable, cliente_cpj: Callable, *, xlsx: Path | None = None,
               executar: bool = False, limite: int | None = None, numero: str | None = None,
               ficha: bool = False, novo_relatorio: bool = False, log: Callable = print,
               confirmar: Callable[[list, list], bool | list] | None = None) -> dict:
    """`conectar()` -> Sessao (só é usado se precisar do Chrome); `cliente_cpj()` -> ClienteCPJ.
    `confirmar(itens, prontas)`: no dry-run, permite executar ESTE plano (modo guiado); se devolver
    uma lista, executa só as tarefas dela."""
    pasta = saida.pasta_da_execucao(Path(cfg["pastas"]["saida"]))
    log = saida.log_com_arquivo(log, pasta / "log.txt")
    audit = saida.Auditoria(pasta / "auditoria.jsonl")
    audit("inicio", modo="EXECUTAR" if executar else "dry-run", xlsx=str(xlsx or ""), limite=limite,
          numero=numero, ficha=ficha)
    sess = None
    itens: list[Item] = []
    try:
        # 1-2) tarefas
        if ficha:
            if not numero:
                raise ValueError("a consulta pela ficha precisa do nº do processo")
            from .fluxos import processo
            sess = conectar()
            log(f"Lendo as tarefas em aberto do processo {numero} na ficha do eLaw...")
            tarefas = processo.tarefas_em_aberto(sess.page, numero)
            for t in tarefas:   # a regra usa a data de REGISTRO (na ficha, só no modal "Ver")
                if _fila(t, cfg):
                    t.data = processo.data_registrado(sess.page, t.id_tarefa)
            audit("ficha", numero=numero, tarefas=len(tarefas))
        else:
            if xlsx is None:
                sess = conectar()
                xlsx = _obter_relatorio(cfg, sess, log, audit, novo_relatorio)
                if xlsx is None:
                    log("Nenhuma tarefa pendente no eLaw com esses filtros. Nada a fazer.")
                    return _fechar(itens, pasta, audit, False, None)
            tarefas, info = ler_tarefas(Path(xlsx), cfg.get("colunas"))
            audit("xlsx_lido", arquivo=str(xlsx), linhas=len(tarefas), **info)
            log(f"Relatório lido: aba '{info['aba']}', cabeçalho na linha {info['linha_cabecalho']}, "
                f"{len(tarefas)} linha(s).")
        # 3) plano
        itens, cont = montar_plano(tarefas, cfg, numero)
        if any(not it.situacao for it in itens):
            log("Entrando na API do CPJ (somente leitura)...")
            avaliar_no_cpj(itens, cliente_cpj(), cfg, log, audit)
        cli = None
        prontas = [it for it in itens if it.situacao == R.PRONTA]
        if limite is not None:
            for it in prontas[limite:]:
                it.situacao, it.detalhe = R.NAO_EXECUTADA, f"fora do --limite {limite}"
            prontas = prontas[:limite]
        saida.gravar_csv(itens, pasta / "plano.csv")
        audit("plano", **cont, itens=len(itens), prontas=len(prontas))
        log(f"\nPlano: {len(itens)} tarefa(s) nas filas (ignoradas: {cont['outro_assunto']} de outro tipo, "
            f"{cont['nao_pendentes']} não pendentes)")
        for it in itens:
            acao = f"{it.situacao}/{it.acao}" if it.acao else it.situacao
            log(f"  [{acao:>32}] {it.fila:<11} {it.numero or '?':<26} tarefa {it.id_tarefa or '-':<8} "
                f"{Path(it.pdf).name if it.pdf else ''}")

        if not executar and confirmar is not None and prontas:
            ok = confirmar(itens, prontas)
            if isinstance(ok, list):
                prontas, ok = ok, bool(ok)
            if ok:
                executar = True
                audit("confirmado_pelo_operador", prontas=len(prontas))
        if not executar:
            log(f"\nDRY-RUN: nada foi feito no eLaw. {len(prontas)} tarefa(s) seriam concluídas "
                f"(acrescente --executar para concluir).")
            return _fechar(itens, pasta, audit, False, None)

        # 4) execução
        if sess is None:
            sess = conectar()
        cli = cliente_cpj() if any(it.cpj_doc for it in prontas) else None
        ex = Execucao(sess.page, cfg, cli, pasta, log)
        erros_seguidos, motivo_abortar = 0, None
        for n, it in enumerate(prontas, 1):
            log(f"\n({n}/{len(prontas)}) [{it.fila}] {it.numero} tarefa {it.id_tarefa} -> {it.acao}")
            try:
                ex.executar(it)
            except NaoAutenticado as e:
                it.situacao, it.detalhe = R.NAO_EXECUTADA, str(e)
                motivo_abortar = "sessão do eLaw expirou"
            audit("tarefa", **asdict(it))
            if it.situacao in (R.ERRO, R.NAO_CONCLUIU):
                erros_seguidos += 1
            elif it.situacao != R.NAO_EXECUTADA:
                erros_seguidos = 0
            if motivo_abortar is None and not esta_logado(sess.page):
                motivo_abortar = "sessão do eLaw expirou"
            if motivo_abortar is None and erros_seguidos >= cfg["tarefa"]["max_erros_seguidos"]:
                motivo_abortar = f"{erros_seguidos} erros seguidos (a tela mudou? o eLaw está instável?)"
            if motivo_abortar:
                for resto in prontas[n:]:
                    resto.situacao, resto.detalhe = R.NAO_EXECUTADA, f"lote abortado: {motivo_abortar}"
                audit("abortado", motivo=motivo_abortar)
                log(f"\n[!] Lote abortado: {motivo_abortar}.")
                break
        return _fechar(itens, pasta, audit, True, motivo_abortar)
    except Exception as e:
        audit("falha", erro=f"{type(e).__name__}: {e}")
        if itens:
            saida.gravar_csv(itens, pasta / "plano.csv")
        raise
    finally:
        if sess is not None:
            sess.fechar()


def _fechar(itens: list[Item], pasta: Path, audit: Callable, executado: bool, abortado: str | None) -> dict:
    if executado:
        saida.gravar_csv(itens, pasta / "resultado.csv")
    n_voce = saida.gravar_precisa_de_voce(itens, pasta / "PRECISA DE VOCE.xlsx")
    resumo: dict[str, int] = {}
    for it in itens:
        chave = f"{it.situacao}/{it.acao}" if it.situacao == R.PRONTA and it.acao else it.situacao
        resumo[chave] = resumo.get(chave, 0) + 1
    audit("fim", executado=executado, abortado=abortado, precisa_de_voce=n_voce, **resumo)
    return {"pasta": str(pasta), "executado": executado, "resumo": resumo, "itens": itens,
            "abortado": abortado, "precisa_de_voce": n_voce}
