"""Normalização de texto usada para comparar rótulos, nomes de arquivo e colunas."""
from __future__ import annotations
import re
import unicodedata


def sem_acento(texto: str | None) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    return "".join(c for c in t if not unicodedata.combining(c))


def norm(texto) -> str:
    """minúsculas, sem acento, sem '.'/':' e com espaços colapsados ('Nº do Processo:' -> 'no do processo')."""
    t = sem_acento(texto).lower().replace(".", " ").replace(":", " ")
    return " ".join(t.split())


def chave_nome(nome: str | None) -> str:
    """Nome de arquivo comparável: só letras e dígitos, sem acento/caixa. O GED do eLaw tira os
    acentos ('Contestação - X.pdf' vira 'Contestacao - X.pdf'), então comparar o nome cru falha."""
    return re.sub(r"[^a-z0-9]", "", sem_acento(nome).lower())
