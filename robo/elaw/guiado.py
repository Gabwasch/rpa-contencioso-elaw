"""
Modo guiado (sem argumentos): um menu simples para o operador do dia a dia.

  1. Rodada do dia  -> monta o plano (dry-run), mostra o resumo por fila e faz DUAS perguntas S/N
                       separadas: "Concluir as N prontas?" e "Reagendar as M sem contestação no CPJ?".
                       Executa ESSE plano (só a parte confirmada), sem gerar o relatório de novo; no fim
                       abre a planilha da rodada (abas 'Precisa de você' e 'Feito pelo robô').
  2. Consultar um processo -> situação de cada tarefa em português; "Concluir/Reagendar? [S/N]"
  3. Abrir a última planilha da rodada (precisa de você / feito pelo robô)
  Enter sai.
"""
from __future__ import annotations
import os
from collections import Counter
from pathlib import Path
from typing import Callable

from . import orquestrador, regras as R, saida
from .conexao import ChromeNaoEncontrado, NaoAutenticado


def _perguntar(texto: str) -> bool:
    return input(texto).strip().lower() in ("s", "sim", "y")


def _quantas(n: int, uma: str, varias: str) -> str:
    return uma if n == 1 else varias.format(n=n)


def _reagendar(it) -> bool:
    return it.situacao == R.PRONTA and it.acao == R.REAGENDAR


def confirmar_rodada(itens: list, prontas: list, perguntar: Callable[[str], bool] = _perguntar) -> list:
    """Concluir as prontas e reagendar são decisões SEPARADAS: duas perguntas S/N.
    Devolve só a parte confirmada (na ordem do plano). Reagendamento recusado volta a ser o que era
    antes (ex.: 'aguardando_peca'): a tarefa não fica marcada como pronta sem ninguém ter decidido."""
    por_acao = Counter(it.acao for it in prontas)
    aguardando = sum(1 for it in itens if it.situacao in R.AGUARDANDO)
    voce = sum(1 for it in itens if R.precisa_de_voce(it.situacao, it.acao, it.antes))
    print(f"\n  Prontas: {len(prontas)} {dict(por_acao)} · aguardando: {aguardando} · precisam de você: {voce}")
    normais = [it for it in prontas if not _reagendar(it)]
    reag = [it for it in prontas if _reagendar(it)]
    sim: list = []
    if normais and perguntar(f"  Concluir {_quantas(len(normais), 'a tarefa pronta', 'as {n} prontas')} agora? [S/N]: "):
        sim += normais
    if reag:
        if perguntar(f"  Reagendar {_quantas(len(reag), 'a tarefa', 'as {n}')} sem contestação no CPJ "
                     "(o eLaw abre um prazo novo)? [S/N]: "):
            sim += reag
        else:   # não reagendar: volta a ser só "aguardando" (ou o problema que já era)
            for it in reag:
                it.situacao, it.acao, it.antes = it.antes, "", ""
    escolhidas = {id(it) for it in sim}
    return [it for it in prontas if id(it) in escolhidas]


def confirmar_consulta(itens: list, prontas: list, perguntar: Callable[[str], bool] = _perguntar) -> bool:
    verbo = "Reagendar" if all(_reagendar(it) for it in prontas) else "Concluir"
    return perguntar(f"  {verbo} {_quantas(len(prontas), 'a tarefa pronta', 'as {n} prontas')} agora? [S/N]: ")


def resumo_da_rodada(itens: list) -> str:
    """Uma linha para o operador: o que o robô fez, o que ficou para depois e o que é com ele."""
    cont = Counter(it.situacao for it in itens)
    concluidas = cont[R.CONCLUIDA] + cont[R.CONCLUIDA_JA_ANEXADA]
    partes = [f"{concluidas} concluídas pelo robô"]
    if cont[R.REAGENDADA]:
        partes.append(f"{cont[R.REAGENDADA]} reagendadas")
    if cont[R.JA_CONCLUIDA]:
        partes.append(f"{cont[R.JA_CONCLUIDA]} já estavam concluídas")
    if cont[R.PRONTA]:   # prontas que o operador respondeu N
        partes.append(f"{cont[R.PRONTA]} prontas ficaram para outra rodada")
    partes.append(f"{sum(cont[s] for s in R.AGUARDANDO)} aguardando")
    partes.append(f"{sum(R.precisa_de_voce(it.situacao, it.acao, it.antes) for it in itens)} precisam de você")
    return " · ".join(partes)


def ultima_planilha(pasta_saida: Path) -> Path | None:
    """A planilha da rodada mais recente em <saida>/<data-hora>/."""
    listas = sorted(Path(pasta_saida).glob(f"*/{saida.ARQUIVO_RODADA}"), key=lambda p: p.stat().st_mtime)
    return listas[-1] if listas else None


def _abrir(arq: Path) -> None:
    try:
        os.startfile(arq)          # type: ignore[attr-defined]  # só existe no Windows
    except (AttributeError, OSError):
        pass                       # fora do Windows (ou sem Excel): o caminho já foi mostrado


def main(cfg: dict, conectar: Callable, cliente_cpj: Callable) -> int:
    print("=== Robô eLaw — contestações e audiências (modo guiado) ===")
    print("O robô não faz login: entre no eLaw pelo Chrome do robô antes de continuar.\n")
    while True:
        op = input("  1 Rodada do dia · 2 Consultar um processo · "
                   "3 Abrir a última planilha da rodada (precisa de você / feito pelo robô) · Enter sai: ").strip()
        if not op:
            return 0
        if op == "3":
            arq = ultima_planilha(cfg["pastas"]["saida"])
            if arq is None:
                print("  Ainda não há planilha de rodada.\n")
            else:
                print(f"  Abrindo {arq}\n")
                _abrir(arq)
            continue
        try:
            if op == "1":
                r = orquestrador.orquestrar(cfg, conectar, cliente_cpj, confirmar=confirmar_rodada)
            elif op == "2":
                numero = input("  Nº do processo: ").strip()
                if not numero:
                    continue
                r = orquestrador.orquestrar(cfg, conectar, cliente_cpj, numero=numero, ficha=True,
                                            confirmar=confirmar_consulta)
            else:
                continue
        except (NaoAutenticado, ChromeNaoEncontrado) as e:
            print(f"\n  [!] {e}\n")
            continue
        except LookupError as e:
            print(f"\n  [!] {e}\n")
            continue
        print(f"\n  Resultado: {resumo_da_rodada(r['itens'])}")
        print(f"  Planilha da rodada (abas 'Precisa de você' e 'Feito pelo robô'): {r['planilha']}\n")
        if op == "1" and (r["precisa_de_voce"] or r["feitas_pelo_robo"]):
            _abrir(Path(r["planilha"]))
