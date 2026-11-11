"""Arquivos de cada execução: plano.csv, resultado.csv, auditoria.jsonl, log.txt e a planilha da rodada
(PRECISA DE VOCE.xlsx, abas 'Precisa de você' e 'Feito pelo robô')."""
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


ARQUIVO_RODADA = "PRECISA DE VOCE.xlsx"
ABA_VOCE, ABA_FEITO = "Precisa de você", "Feito pelo robô"
NOME_FILA = {"contestacao": "Anexar contestação", "audiencia": "Confirmar audiência"}


def o_que_o_robo_fez(it) -> str:
    """Frase curta do que o robô gravou no eLaw nesta tarefa (aba 'Feito pelo robô')."""
    if it.fila == "audiencia":
        resultado = it.resultado or (it.detalhe or "").split(";")[0]
        return f"Audiência confirmada como {resultado}" + (" e ata anexada" if it.anexo else " (sem ata)")
    if it.situacao == R.CONCLUIDA:
        return "Contestação anexada e tarefa concluída"
    if it.situacao == R.CONCLUIDA_JA_ANEXADA:
        return "Tarefa concluída como 'Já anexada' (a contestação já estava no eLaw)"
    if it.situacao == R.REAGENDADA:
        return ("Reagendada: concluída com 'Prazo de contestação em curso' "
                "(sem contestação no CPJ; o eLaw abriu uma tarefa nova)")
    return it.situacao


def _aba(ws, cabecalho: list[str], linhas: list[list], larguras: tuple[int, ...], vazio: str) -> None:
    from openpyxl.styles import Alignment, Font, PatternFill
    ws.append(cabecalho)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="1F3B5B")
    for ln in linhas:
        ws.append(ln)
    if not linhas:
        ws.append([vazio])
    for i, largura in enumerate(larguras):
        ws.column_dimensions[chr(ord("A") + i)].width = largura
    for row in ws.iter_rows(min_row=2):
        for c in row:
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "A2"


def gravar_planilha_da_rodada(itens: list, arq: Path, quando: datetime | None = None) -> tuple[int, int]:
    """A planilha da rodada, com duas abas:
      - 'Precisa de você': só o que pede ação humana, com o que fazer em português simples;
      - 'Feito pelo robô': o que o robô gravou no eLaw (processo, tarefa, o que fez, PDF, ID no GED).
    Se nada precisa da equipe mas o robô fez algo, a planilha abre direto na aba do que foi feito.
    Devolve (nº de linhas 'precisa de você', nº de linhas 'feito pelo robô')."""
    from openpyxl import Workbook
    voce = [it for it in itens if R.precisa_de_voce(it.situacao, it.acao, it.antes)]
    feitas = [it for it in itens if R.feita_pelo_robo(it.situacao)]
    wb = Workbook()
    ws = wb.active
    ws.title = ABA_VOCE
    _aba(ws, ["Processo", "Tarefa", "Fila", "O que fazer", "Detalhe (para o suporte)"],
         [[it.numero, it.id_tarefa, NOME_FILA.get(it.fila, it.fila),
           R.o_que_fazer(it.situacao, it.detalhe, it.anexo, it.antes, it.acao), it.detalhe] for it in voce],
         (28, 12, 20, 80, 70), "Nada precisa de você nesta rodada.")
    data = (quando or datetime.now()).strftime("%d/%m/%Y %H:%M")
    _aba(wb.create_sheet(ABA_FEITO),
         ["Data da rodada", "Processo", "Tarefa", "Fila", "O que o robô fez", "PDF", "Anexo no eLaw (GED)"],
         [[data, it.numero, it.id_tarefa, NOME_FILA.get(it.fila, it.fila), o_que_o_robo_fez(it),
           Path(it.pdf).name if it.pdf else "", it.anexo] for it in feitas],
         (17, 28, 12, 20, 70, 45, 20), "O robô não gravou nada no eLaw nesta rodada.")
    if not voce and feitas:
        wb.active = 1          # nada para a equipe: abre direto no que foi feito
    wb.save(arq)
    return len(voce), len(feitas)
