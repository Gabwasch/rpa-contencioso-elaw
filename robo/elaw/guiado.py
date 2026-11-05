"""
Modo guiado (sem argumentos): um menu simples para o operador do dia a dia.

  1. Rodada do dia  -> monta o plano (dry-run), mostra o resumo por fila e pergunta
                       "Concluir as N prontas agora?" — executa ESSE plano, sem gerar o relatório de novo
  2. Consultar um processo -> situação de cada tarefa em português; "Concluir? [S/N]"
  Enter sai.
"""
from __future__ import annotations
from collections import Counter
from typing import Callable

from . import orquestrador, regras as R
from .conexao import ChromeNaoEncontrado, NaoAutenticado


def _perguntar(texto: str) -> bool:
    return input(texto).strip().lower() in ("s", "sim", "y")


def _confirmar(itens: list, prontas: list) -> list:
    por_acao = Counter(it.acao for it in prontas)
    aguardando = sum(1 for it in itens if it.situacao in R.AGUARDANDO)
    voce = sum(1 for it in itens if R.precisa_de_voce(it.situacao, it.acao, it.antes))
    print(f"\n  Prontas: {len(prontas)} {dict(por_acao)} · aguardando: {aguardando} · precisam de você: {voce}")
    escolhidas = [it for it in prontas if it.acao != R.REAGENDAR]
    if escolhidas and not _perguntar(f"  Concluir as {len(escolhidas)} prontas agora? [S/N]: "):
        escolhidas = []
    reag = [it for it in prontas if it.acao == R.REAGENDAR]
    if reag and _perguntar(f"  Reagendar as {len(reag)} sem contestação no CPJ (o eLaw abre um prazo novo)? [S/N]: "):
        escolhidas += reag
    return escolhidas


def main(cfg: dict, conectar: Callable, cliente_cpj: Callable) -> int:
    print("=== Robô eLaw — contestações e audiências (modo guiado) ===")
    print("O robô não faz login: entre no eLaw pelo Chrome do robô antes de continuar.\n")
    while True:
        op = input("  1 Rodada do dia · 2 Consultar um processo · Enter sai: ").strip()
        if not op:
            return 0
        try:
            if op == "1":
                r = orquestrador.orquestrar(cfg, conectar, cliente_cpj, confirmar=_confirmar)
            elif op == "2":
                numero = input("  Nº do processo: ").strip()
                if not numero:
                    continue
                r = orquestrador.orquestrar(cfg, conectar, cliente_cpj, numero=numero, ficha=True,
                                            confirmar=lambda itens, prontas: _perguntar(
                                                f"  Concluir {len(prontas)} tarefa(s) pronta(s)? [S/N]: "))
            else:
                continue
        except (NaoAutenticado, ChromeNaoEncontrado) as e:
            print(f"\n  [!] {e}\n")
            continue
        except LookupError as e:
            print(f"\n  [!] {e}\n")
            continue
        print(f"\n  Resultado: {r['resumo']}")
        print(f"  Precisam de você: {r['precisa_de_voce']} (lista em {r['pasta']}\\PRECISA DE VOCE.xlsx)\n")
