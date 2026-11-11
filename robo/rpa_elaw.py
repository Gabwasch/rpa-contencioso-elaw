#!/usr/bin/env python
"""
Robô de contencioso no eLaw — ponto de entrada.

O robô NÃO faz login: ele se acopla (CDP) ao Chrome em que o operador já entrou no eLaw
passando pelo SSO/MFA corporativo.

    python rpa_elaw.py                                  # modo guiado (menu)
    python rpa_elaw.py orquestrar                       # rodada completa em DRY-RUN
    python rpa_elaw.py orquestrar --executar [--limite N] [--numero CNJ]
    python rpa_elaw.py consultar --numero CNJ [--executar]
    python rpa_elaw.py relatorio-tarefas [--status pendentes,atrasados] [--tipo "Anexar contestação"]
    python rpa_elaw.py anexar --numero CNJ --arquivo peca.pdf [--tipo 31] [--ensaio]
    python rpa_elaw.py buscar --numero CNJ

Códigos de saída: 0 ok · 1 não concluiu / lote abortado por erros · 2 Chrome ausente ou sessão
não autenticada/expirada · 3 o eLaw recusou (pesquisa/relatório/tipo) · 4 anexo com o mesmo nome
já existe · 5 processo não encontrado · 6 API do CPJ indisponível.
"""
from __future__ import annotations
import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
for _fluxo in (sys.stdout, sys.stderr):   # acentos no console do Windows
    try:
        _fluxo.reconfigure(encoding="utf-8")
    except Exception:
        pass

from elaw import config, orquestrador  # noqa: E402
from elaw import regras as R  # noqa: E402
from elaw.conexao import ChromeNaoEncontrado, NaoAutenticado, conectar  # noqa: E402
from elaw.cpj import ClienteCPJ, CPJIndisponivel, carregar_credenciais  # noqa: E402
from elaw.fluxos.concluir import JaAnexado  # noqa: E402
from elaw.fluxos.processo import ProcessoNaoEncontrado  # noqa: E402
from elaw.fluxos.relatorio import RelatorioIndisponivel  # noqa: E402
from elaw.fluxos.tarefas import ErroPesquisa, STATUS_POR_NOME  # noqa: E402

OK, NAO_CONCLUIU, SEM_SESSAO, RECUSADO, JA_EXISTE, NAO_ENCONTRADO, CPJ_FORA = 0, 1, 2, 3, 4, 5, 6


def _conector(cfg: dict, args):
    cdp = args.cdp or cfg["chrome"]["cdp"]
    return lambda: conectar(cdp, cfg["elaw"]["base_url"], slow_mo=args.slow_mo)


def _cliente_cpj(cfg: dict):
    def criar() -> ClienteCPJ:
        login, senha = carregar_credenciais(cfg["cpj"]["arquivo_env"])
        return ClienteCPJ(cfg["cpj"]["base_url"], login, senha, cfg["cpj"].get("grupo_trabalho"))
    return criar


def _mostrar_resumo(r: dict) -> None:
    print(f"\nResumo: {r['resumo']}")
    print(f"Precisam de você: {r['precisa_de_voce']} · feitas pelo robô: {r['feitas_pelo_robo']}  ->  "
          f"{r['planilha']} (abas 'Precisa de você' e 'Feito pelo robô')")
    print(f"Arquivos da execução: {r['pasta']}")


def _codigo_do_lote(r: dict) -> int:
    if r.get("abortado"):
        return SEM_SESSAO if "sessão" in r["abortado"] else NAO_CONCLUIU
    return OK


# ---------------------------------------------------------------- subcomandos
def cmd_orquestrar(cfg, args) -> int:
    r = orquestrador.orquestrar(
        cfg, _conector(cfg, args), _cliente_cpj(cfg), xlsx=Path(args.xlsx) if args.xlsx else None,
        executar=args.executar, limite=args.limite, numero=args.numero, novo_relatorio=args.novo_relatorio)
    _mostrar_resumo(r)
    return _codigo_do_lote(r)


def cmd_consultar(cfg, args) -> int:
    r = orquestrador.orquestrar(cfg, _conector(cfg, args), _cliente_cpj(cfg), executar=args.executar,
                                numero=args.numero, ficha=True)
    if not r["itens"]:
        print("\nNenhuma tarefa de 'Anexar contestação' ou 'Confirmar audiência' em aberto neste processo.")
    for it in r["itens"]:
        print(f"  tarefa {it.id_tarefa}: {it.situacao}{'/' + it.acao if it.acao else ''} — {it.detalhe}")
        if R.precisa_de_voce(it.situacao, it.acao, it.antes):
            print(f"    PRECISA DE VOCÊ: {R.o_que_fazer(it.situacao, it.detalhe, it.anexo, it.antes, it.acao)}")
    _mostrar_resumo(r)
    return _codigo_do_lote(r)


def _data(txt: str) -> date:
    try:
        return datetime.strptime(txt, "%d/%m/%Y").date()
    except ValueError:
        raise SystemExit(f"Data inválida '{txt}' (use dd/mm/aaaa).") from None


def cmd_relatorio_tarefas(cfg, args) -> int:
    from elaw.fluxos import relatorio, tarefas
    nomes = [s.strip().lower() for s in args.status.split(",") if s.strip()]
    invalidos = [n for n in nomes if n not in STATUS_POR_NOME]
    if invalidos:
        raise SystemExit(f"Status inválido: {', '.join(invalidos)}. Use: {', '.join(STATUS_POR_NOME)}")
    ate = _data(args.ate) if args.ate else date.today()
    de = _data(args.de) if args.de else ate - timedelta(days=cfg["relatorio"]["dias_antes"])
    sess = _conector(cfg, args)()
    try:
        print(f"Tarefas {'+'.join(nomes)} | tipo: {args.tipo or 'todos'} | cadastradas de {de:%d/%m/%Y} a {ate:%d/%m/%Y}")
        r = tarefas.gerar_relatorio(sess.page, Path(args.out or cfg["pastas"]["relatorios"]),
                                    cfg["relatorio"]["template_tarefas"], [STATUS_POR_NOME[n] for n in nomes],
                                    [args.tipo] if args.tipo else [], de, ate, cfg["relatorio"]["tipo_data"])
    finally:
        sess.fechar()
    if r.get("vazio"):
        print("Nenhum registro com esses filtros: nada foi gerado.")
        return OK
    if not r.get("ok"):
        print(f"[!] {r.get('motivo')}", file=sys.stderr)
        return NAO_CONCLUIU
    r = relatorio.renomear(r, f"tarefas_{date.today():%Y-%m-%d}_{'-'.join(nomes)}")
    print(f"Relatório {r['id_relatorio']} baixado: {r['arquivo']} ({r['bytes']} bytes)")
    return OK


def cmd_anexar(cfg, args) -> int:
    from elaw.fluxos import anexar
    sess = _conector(cfg, args)()
    try:
        r = anexar.anexar(sess.page, args.numero, Path(args.arquivo), args.tipo, ensaio=args.ensaio)
    except JaAnexado as e:
        print(f"[!] {e}. Nada foi enviado.", file=sys.stderr)
        return JA_EXISTE
    finally:
        sess.fechar()
    if r.get("ensaio"):
        print(f"Ensaio OK: modal aberto, Tipo '{r['tipo']}' escolhido e cancelado (nada enviado).")
    elif r["ok"]:
        print(f"Anexado: GED {r['id_anexo']} | {r['anexo']['nome']} | {r['anexo']['tipo']} | {r['anexo']['data']}")
    else:
        print("[!] Salvei, mas não achei o anexo novo na lista. Confira a aba Anexos.", file=sys.stderr)
        return NAO_CONCLUIU
    return OK


def cmd_buscar(cfg, args) -> int:
    from elaw.fluxos import processo
    sess = _conector(cfg, args)()
    try:
        linhas = processo.buscar(sess.page, args.numero)
    finally:
        sess.fechar()
    print(f"Encontrados: {len(linhas)}")
    for l in linhas[:10]:
        print(f"  ID {l['id']} | {l['numero']} | {l['parte']} | {l['status']}")
    return OK if linhas else NAO_ENCONTRADO


# ---------------------------------------------------------------- CLI
def criar_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="rpa_elaw", description="Robô de contencioso no eLaw (acopla na sessão do operador)")
    ap.add_argument("--config", help="caminho do config.toml (padrão: ao lado do robô)")
    ap.add_argument("--cdp", help="URL do Chrome com depuração remota (padrão: [chrome] cdp)")
    ap.add_argument("--slow-mo", type=int, default=0, help="atraso (ms) entre ações, para assistir ao robô")
    sub = ap.add_subparsers(dest="cmd")

    o = sub.add_parser("orquestrar", help="rodada completa: relatório -> CPJ -> regras -> (executa)")
    o.add_argument("--executar", action="store_true", help="CONCLUI as tarefas no eLaw (sem isto: dry-run)")
    o.add_argument("--limite", type=int, help="conclui no máximo N tarefas (piloto)")
    o.add_argument("--numero", help="só as tarefas deste nº de processo")
    o.add_argument("--xlsx", help="usa este relatório já baixado em vez de gerar um")
    o.add_argument("--novo-relatorio", action="store_true", help="gera um relatório novo mesmo se já houver um de hoje")
    o.set_defaults(func=cmd_orquestrar)

    c = sub.add_parser("consultar", help="UM processo, sem relatório: tarefas da ficha + CPJ")
    c.add_argument("--numero", required=True)
    c.add_argument("--executar", action="store_true", help="conclui as tarefas prontas deste processo")
    c.set_defaults(func=cmd_consultar)

    rt = sub.add_parser("relatorio-tarefas", help="gera e baixa o relatório de tarefas")
    rt.add_argument("--status", default="pendentes,atrasados", help="separados por vírgula: " + ", ".join(STATUS_POR_NOME))
    rt.add_argument("--tipo", help="Tipo de Tarefa pelo nome ou pelo código")
    rt.add_argument("--de", help="cadastradas a partir de dd/mm/aaaa")
    rt.add_argument("--ate", help="cadastradas até dd/mm/aaaa (padrão: hoje)")
    rt.add_argument("--out", help="pasta de destino")
    rt.set_defaults(func=cmd_relatorio_tarefas)

    an = sub.add_parser("anexar", help="anexa um PDF avulso ao processo (ESCRITA)")
    an.add_argument("--numero", required=True)
    an.add_argument("--arquivo", required=True)
    an.add_argument("--tipo", default="31", help="código do Tipo de Documento (padrão: 31 = Contestação)")
    an.add_argument("--ensaio", action="store_true", help="abre o modal, escolhe o Tipo e CANCELA")
    an.set_defaults(func=cmd_anexar)

    b = sub.add_parser("buscar", help="pesquisa um processo (somente leitura)")
    b.add_argument("--numero", required=True)
    b.set_defaults(func=cmd_buscar)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = criar_parser().parse_args(argv)
    cfg = config.carregar(args.config)
    if not args.cmd:
        from elaw import guiado
        return guiado.main(cfg, _conector(cfg, args), _cliente_cpj(cfg))
    try:
        return args.func(cfg, args) or OK
    except NaoAutenticado as e:            # inclui SessaoExpirada
        print(f"[!] {e}", file=sys.stderr)
        return SEM_SESSAO
    except ChromeNaoEncontrado as e:
        print(f"[!] {e}", file=sys.stderr)
        return SEM_SESSAO
    except (ErroPesquisa, RelatorioIndisponivel, LookupError) as e:
        if isinstance(e, ProcessoNaoEncontrado):
            print(f"[!] {e}", file=sys.stderr)
            return NAO_ENCONTRADO
        print(f"[!] {e}", file=sys.stderr)
        return RECUSADO
    except CPJIndisponivel as e:
        print(f"[!] {e}", file=sys.stderr)
        return CPJ_FORA


if __name__ == "__main__":
    raise SystemExit(main())
