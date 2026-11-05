import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "robo"), str(RAIZ)]


@pytest.fixture
def app_mock():
    """App do mock com a API do CPJ estável (sem 503 simulados)."""
    from mock.app import criar_app
    return criar_app(instavel=False)


@pytest.fixture
def cliente_cpj(app_mock):
    """ClienteCPJ real falando com o mock via TestClient (sem rede, sem pausas)."""
    from fastapi.testclient import TestClient
    from elaw.cpj import ClienteCPJ
    return ClienteCPJ("http://testserver/cpj", "robo.leitura", "cpj-demo-123", grupo_trabalho=700,
                      sessao=TestClient(app_mock), pausa=lambda s: None)
