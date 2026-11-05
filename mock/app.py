"""
Mock executável (um processo só): interface "parecida com o eLaw" + API "parecida com a do CPJ".

    python -m mock.app            # sobe em http://127.0.0.1:8701  (login: operador / demo123)

Tudo aqui é fictício. Os ids dos elementos têm trechos j_id_* sorteados a cada início,
como no JSF/PrimeFaces de verdade — o robô só funciona porque mira em sufixos estáveis.
"""
from __future__ import annotations
import argparse
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import cpj_api, elaw_ui
from .estado import DADOS, Estado

PORTA_PADRAO = 8701


def criar_app(dados: Path = DADOS, **opcoes) -> FastAPI:
    """`opcoes` vão para o Estado (ex.: instavel=False, limite_token=5, hoje=date(...))."""
    if not Path(dados).exists():
        from . import seed
        seed.main()
    estado = Estado(dados, **opcoes)
    app = FastAPI(title="Mock eLaw + CPJ (dados fictícios)", docs_url="/cpj/docs", redoc_url=None)
    app.state.estado = estado
    app.include_router(cpj_api.criar_router(estado))
    app.include_router(elaw_ui.criar_router(estado))
    app.mount("/static", StaticFiles(directory=Path(__file__).with_name("static")), name="static")
    return app


def main() -> None:
    import uvicorn
    ap = argparse.ArgumentParser(description="Mock do eLaw + CPJ (dados fictícios)")
    ap.add_argument("--porta", type=int, default=PORTA_PADRAO)
    ap.add_argument("--estavel", action="store_true", help="desliga os 503 simulados da API do CPJ")
    args = ap.parse_args()
    print(f"Mock no ar: http://127.0.0.1:{args.porta}  (login: operador / demo123)")
    uvicorn.run(criar_app(instavel=not args.estavel), host="127.0.0.1", port=args.porta, log_level="warning")


if __name__ == "__main__":
    main()
