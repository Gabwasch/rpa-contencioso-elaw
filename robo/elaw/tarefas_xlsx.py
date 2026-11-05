"""
Leitura do relatório de tarefas (xlsx) exportado do eLaw.

O relatório tem linhas de título antes do cabeçalho (e a posição muda conforme o modelo),
então o parser ACHA o cabeçalho sozinho: testa as primeiras linhas de cada aba e fica com
a que reconhece mais colunas pelos apelidos do config.toml [colunas]. Se a coluna do nº
do processo não for reconhecida, cai para "qualquer célula com padrão CNJ" da linha.
"""
from __future__ import annotations
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook

from . import cnj
from .texto import norm

CAMPOS = ("numero", "assunto", "status", "id_tarefa", "data")

APELIDOS_PADRAO = {
    "numero": ["numero do processo", "numero processo", "no processo"],
    "assunto": ["sub tipo", "subtipo", "assunto"],
    "status": ["tarefa - status", "status", "situacao"],
    "id_tarefa": ["tarefa - id", "id da tarefa", "id tarefa"],
    "data": ["data registrado", "cadastro", "data"],
}


@dataclass
class Tarefa:
    linha: int                  # linha no xlsx (1-based, para auditoria)
    numero: str | None
    assunto: str
    status: str
    id_tarefa: str | None
    data: str                   # data de REGISTRO (entrada) da tarefa, dd/mm/aaaa
    texto: str = field(repr=False, default="")   # a linha inteira (fallback de busca)


def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (datetime, date)):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v).strip()


def mapear_colunas(cabecalho: list[str], apelidos: dict[str, list[str]]) -> dict[str, int]:
    """campo -> índice da coluna. Para cada apelido (em ordem), tenta igualdade e depois 'contém'."""
    cab = [norm(c) for c in cabecalho]
    mapa: dict[str, int] = {}
    usados: set[int] = set()
    for campo in CAMPOS:
        for apelido in apelidos.get(campo, []):
            a = norm(apelido)
            idx = next((i for i, c in enumerate(cab) if c == a and i not in usados), None)
            if idx is None:
                idx = next((i for i, c in enumerate(cab) if a and a in c and i not in usados), None)
            if idx is not None:
                mapa[campo] = idx
                usados.add(idx)
                break
    return mapa


def ler_tarefas(caminho: Path, apelidos: dict[str, list[str]] | None = None,
                max_linhas_cabecalho: int = 20) -> tuple[list[Tarefa], dict]:
    """(tarefas, info). `info` traz a aba, a linha do cabeçalho e as colunas reconhecidas."""
    apelidos = apelidos or APELIDOS_PADRAO
    with warnings.catch_warnings():   # xlsx gerado por sistema costuma vir sem estilo padrão
        warnings.simplefilter("ignore")
        wb = load_workbook(caminho, read_only=True, data_only=True)
    try:
        melhor = None   # (pontos, aba, nº da linha, cabeçalho, mapa)
        for ws in wb.worksheets:
            for i, row in enumerate(ws.iter_rows(max_row=max_linhas_cabecalho, values_only=True), 1):
                cab = [_txt(v) for v in row]
                mapa = mapear_colunas(cab, apelidos)
                pontos = len(mapa) + (2 if "numero" in mapa else 0)
                if len(mapa) >= 2 and (melhor is None or pontos > melhor[0]):
                    melhor = (pontos, ws.title, i, cab, mapa)
        if melhor is None:
            raise ValueError(f"Não reconheci o cabeçalho de {Path(caminho).name} (ajuste [colunas] no config.toml).")
        _, aba, linha_cab, cab, mapa = melhor

        def cel(row, campo: str) -> str:
            i = mapa.get(campo)
            return _txt(row[i]) if i is not None and i < len(row) else ""

        tarefas = []
        for n, row in enumerate(wb[aba].iter_rows(min_row=linha_cab + 1, values_only=True), linha_cab + 1):
            if not any(v not in (None, "") for v in row):
                continue
            texto = " | ".join(_txt(v) for v in row if v not in (None, ""))
            tarefas.append(Tarefa(
                linha=n, numero=cnj.extrair(cel(row, "numero")) or cnj.extrair(texto),
                assunto=cel(row, "assunto"), status=cel(row, "status"),
                id_tarefa=cel(row, "id_tarefa") or None, data=cel(row, "data"), texto=texto))
        return tarefas, {"aba": aba, "linha_cabecalho": linha_cab, "colunas": {c: cab[i] for c, i in mapa.items()}}
    finally:
        wb.close()
