"""Arquivos de cada execução: plano.csv, resultado.csv, auditoria.jsonl, log.txt e PRECISA DE VOCE.xlsx."""
from __future__ import annotations
import csv
import json
from dataclasses import asdict, fields
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import regras as R


def pasta_da_execucao(raiz: Path) -> Path:
    base = Path(raiz) / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    pasta, n = base, 2
    while pasta.exists():
        pasta = base.with_name(f"{base.name}_{n}")
        n += 1
    pasta.mkdir(parents=True)
    return pasta


def gravar_csv(itens: list, arq: Path) -> None:
    """';' + utf-8-sig: abre direto no Excel em português."""
    if not itens:
        arq.write_text("", encoding="utf-8-sig")
        return
    with open(arq, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=[c.name for c in fields(itens[0])], delimiter=";")
        w.writeheader()
        for it in itens:
            w.writerow(asdict(it))


class Auditoria:
    """Uma linha JSON por evento — o que foi feito, em qual processo, com qual arquivo, quando."""

    def __init__(self, arq: Path):
        self.arq = arq

    def __call__(self, evento: str, **dados) -> None:
        reg = {"ts": datetime.now().isoformat(timespec="seconds"), "evento": evento, **dados}
        with open(self.arq, "a", encoding="utf-8") as f:
            f.write(json.dumps(reg, ensure_ascii=False, default=str) + "\n")


def log_com_arquivo(log: Callable[[str], None], arq: Path) -> Callable[[str], None]:
    def _log(msg: str = "") -> None:
        log(msg)
        try:
            with open(arq, "a", encoding="utf-8") as f:
                f.write(f"{datetime.now():%H:%M:%S} {msg}\n")
        except OSError:
            pass
    return _log


def gravar_precisa_de_voce(itens: list, arq: Path) -> int:
    """Só as linhas que precisam de ação humana, com o que fazer em português simples."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    linhas = [it for it in itens if R.precisa_de_voce(it.situacao, it.acao, it.antes)]
    wb = Workbook()
    ws = wb.active
    ws.title = "Precisa de você"
    ws.append(["Processo", "Tarefa", "Fila", "O que fazer", "Detalhe (para o suporte)"])
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3B5B")
    for it in linhas:
        ws.append([it.numero, it.id_tarefa, it.fila,
                   R.o_que_fazer(it.situacao, it.detalhe, it.anexo, it.antes, it.acao), it.detalhe])
    for col, largura in zip("ABCDE", (28, 12, 13, 80, 70)):
        ws.column_dimensions[col].width = largura
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"
    wb.save(arq)
    return len(linhas)
