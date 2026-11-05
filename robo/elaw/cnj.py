"""
Número único de processo (padrão CNJ, Resolução 65/2008): NNNNNNN-DD.AAAA.J.TR.OOOO

  NNNNNNN  sequencial      AAAA  ano do ajuizamento   J   segmento do Judiciário
  DD       dígitos verificadores (ISO 7064, módulo 97-10)
  TR       tribunal        OOOO  unidade de origem

O robô usa o número para casar o eLaw com o CPJ e para travar PDFs de outro processo.
"""
from __future__ import annotations
import re

RE_CNJ = re.compile(r"(?<!\d)\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}(?!\d)")
# o mesmo número só com dígitos (20), comum em nome de arquivo
RE_CNJ_DIGITOS = re.compile(r"(?<!\d)(\d{7})(\d{2})(\d{4})(\d)(\d{2})(\d{4})(?!\d)")


def so_digitos(texto: str | None) -> str:
    return re.sub(r"\D", "", texto or "")


def digitos_verificadores(sequencial: str, ano: str, segmento: str, tribunal: str, origem: str) -> str:
    """DD = 98 - (N·A·J·TR·O·00 mod 97), com zeros à esquerda."""
    resto = int(f"{sequencial}{ano}{segmento}{tribunal}{origem}00") % 97
    return f"{98 - resto:02d}"


def formatar(numero: str) -> str:
    """Formata 20 dígitos no padrão CNJ (aceita o número já formatado)."""
    d = so_digitos(numero)
    if len(d) != 20:
        raise ValueError(f"Número CNJ precisa de 20 dígitos (recebi {len(d)}): {numero!r}")
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:]}"


def validar(numero: str) -> bool:
    """True se tem 20 dígitos e os dígitos verificadores conferem."""
    d = so_digitos(numero)
    if len(d) != 20:
        return False
    seq, dv, ano, j, tr, origem = d[:7], d[7:9], d[9:13], d[13], d[14:16], d[16:]
    return digitos_verificadores(seq, ano, j, tr, origem) == dv


def gerar(sequencial: int, ano: int, segmento: int, tribunal: int, origem: int) -> str:
    """Monta um número CNJ válido (com os DV calculados) — usado nos testes e na massa fictícia."""
    seq, a, j, tr, o = f"{sequencial:07d}", f"{ano:04d}", f"{segmento}", f"{tribunal:02d}", f"{origem:04d}"
    return f"{seq}-{digitos_verificadores(seq, a, j, tr, o)}.{a}.{j}.{tr}.{o}"


def extrair(texto: str | None) -> str | None:
    """1º número de processo encontrado no texto (formatado ou só dígitos); devolve formatado."""
    m = RE_CNJ.search(texto or "")
    if m:
        return m.group(0)
    m = RE_CNJ_DIGITOS.search(texto or "")
    return "{}-{}.{}.{}.{}.{}".format(*m.groups()) if m else None


def mesmo_processo(a: str | None, b: str | None) -> bool:
    return bool(a and b) and so_digitos(a) == so_digitos(b)
