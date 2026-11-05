"""Carrega o config.toml (ao lado do executável, ou na pasta robo/ em modo dev)."""
from __future__ import annotations
import sys
import tomllib
from pathlib import Path


def pasta_base() -> Path:
    if getattr(sys, "frozen", False):          # empacotado com PyInstaller
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[1]


def _resolver(base: Path, valor: str) -> Path:
    p = Path(valor)
    return p if p.is_absolute() else (base / p).resolve()


def carregar(caminho: str | Path | None = None) -> dict:
    arq = Path(caminho) if caminho else pasta_base() / "config.toml"
    if not arq.exists():
        raise FileNotFoundError(f"Config não encontrado: {arq}")
    with open(arq, "rb") as f:
        cfg = tomllib.load(f)
    base = arq.resolve().parent       # caminhos relativos = relativos ao próprio config.toml
    pastas = cfg.setdefault("pastas", {})
    for chave, padrao in (("relatorios", "../saida/relatorios"), ("saida", "../saida/execucoes")):
        pastas[chave] = _resolver(base, pastas.get(chave, padrao))
    cpj = cfg.setdefault("cpj", {})
    cpj["arquivo_env"] = _resolver(base, cpj.get("arquivo_env", ".env"))
    cfg.setdefault("tarefa", {}).setdefault("max_erros_seguidos", 3)
    return cfg
