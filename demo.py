#!/usr/bin/env python
"""
Demonstração ponta a ponta, em um comando:

    python demo.py                 # com a janela do Chrome visível
    python demo.py --headless      # sem janela
    python demo.py --passo-a-passo # devagar, para assistir ao robô trabalhando

O que acontece:
  1. sobe o MOCK (eLaw + CPJ fictícios) em http://127.0.0.1:8701, numa thread;
  2. abre o Google Chrome instalado (ou o Chromium do Playwright) com um perfil TEMPORÁRIO e a
     porta de depuração 9322 — nenhuma outra janela do Chrome é tocada;
  3. faz o passo HUMANO: o login (no mundo real é o operador, com SSO/MFA; o robô nunca digita senha);
  4. roda o robô em DRY-RUN (só o plano) e depois com --executar;
  5. cenário extra: derruba a sessão e mostra o robô parando com o código 2 (sem tentar logar);
  6. mostra o resumo e onde ficaram os arquivos; fecha SÓ o Chrome que ela mesma abriu.
"""
from __future__ import annotations
import argparse
import csv
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections import Counter
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
PORTA_MOCK = 8701
PORTA_CDP = 9322        # de propósito longe da 9222: não colide com outros Chromes de depuração
URL_MOCK = f"http://127.0.0.1:{PORTA_MOCK}"
URL_CDP = f"http://127.0.0.1:{PORTA_CDP}"
SAIDA = RAIZ / "saida" / "execucoes"

os.system("")   # liga as cores ANSI no console do Windows
for _f in (sys.stdout, sys.stderr):
    try:
        _f.reconfigure(encoding="utf-8")
    except Exception:
        pass
VERDE, AMARELO, VERMELHO, AZUL, CINZA, NEGRITO, FIM = ("\033[32m", "\033[33m", "\033[31m", "\033[36m", "\033[90m",
                                                     "\033[1m", "\033[0m")


def titulo(txt: str) -> None:
    print(f"\n{AZUL}{NEGRITO}{'━' * 78}\n  {txt}\n{'━' * 78}{FIM}", flush=True)


def info(txt: str) -> None:
    print(f"{CINZA}[demo]{FIM} {txt}", flush=True)


def checar_dependencias() -> None:
    faltando = []
    for mod, pacote in (("playwright", "playwright"), ("fastapi", "fastapi"), ("uvicorn", "uvicorn"),
                        ("openpyxl", "openpyxl"), ("requests", "requests"), ("multipart", "python-multipart")):
        try:
            __import__(mod)
        except ImportError:
            faltando.append(pacote)
    if faltando:
        sys.exit(f"Faltam pacotes: {', '.join(faltando)}.  Rode:  pip install -r requirements.txt")


def porta_em_uso(porta: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", porta)) == 0


# ------------------------------------------------------------------ mock
def subir_mock():
    import uvicorn
    sys.path.insert(0, str(RAIZ))
    from mock.app import criar_app
    if porta_em_uso(PORTA_MOCK):
        sys.exit(f"A porta {PORTA_MOCK} já está em uso. Feche o que estiver nela e rode de novo.")
    servidor = uvicorn.Server(uvicorn.Config(criar_app(), host="127.0.0.1", port=PORTA_MOCK, log_level="warning"))
    threading.Thread(target=servidor.run, daemon=True).start()
    for _ in range(100):
        if servidor.started:
            return servidor
        time.sleep(0.1)
    sys.exit("O mock não subiu a tempo.")


# ------------------------------------------------------------------ Chrome
def achar_chrome() -> str | None:
    candidatos = []
    if sys.platform.startswith("win"):
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if os.environ.get(var):
                candidatos.append(Path(os.environ[var]) / "Google/Chrome/Application/chrome.exe")
    elif sys.platform == "darwin":
        candidatos.append(Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"))
    else:
        for nome in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            if shutil.which(nome):
                candidatos.append(Path(shutil.which(nome)))
    for c in candidatos:
        if c.exists():
            return str(c)
    try:   # plano B: o Chromium que o `playwright install chromium` baixa
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            exe = pw.chromium.executable_path
        if exe and Path(exe).exists():
            return exe
    except Exception:
        pass
    return None


def abrir_chrome(exe: str, perfil: Path, headless: bool) -> subprocess.Popen:
    if porta_em_uso(PORTA_CDP):
        sys.exit(f"A porta {PORTA_CDP} já está em uso (outro Chrome de depuração?). A demo não mexe nele: "
                 "feche-o e rode de novo.")
    args = [exe, f"--remote-debugging-port={PORTA_CDP}", f"--user-data-dir={perfil}", "--no-first-run",
            "--no-default-browser-check", "--disable-features=Translate", "--disable-component-update",
            "--disable-background-networking", "--disable-sync", "--window-size=1366,900",
            f"{URL_MOCK}/login.elaw"]
    if headless:
        args.insert(1, "--headless=new")
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"{URL_CDP}/json/version", timeout=1):
                return proc
        except Exception:
            time.sleep(0.5)
    fechar_chrome(proc, perfil)
    sys.exit("O Chrome abriu, mas a porta de depuração não respondeu.")


def fechar_chrome(proc: subprocess.Popen, perfil: Path) -> None:
    """Encerra SÓ o Chrome que a demo abriu (e os processos-filho dele)."""
    if proc.poll() is None:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
    for _ in range(10):   # o Windows segura arquivos do perfil por alguns instantes
        shutil.rmtree(perfil, ignore_errors=True)
        if not perfil.exists():
            break
        time.sleep(0.5)


def login_humano(passo_a_passo: bool) -> None:
    """O passo que, no mundo real, é do OPERADOR (SSO/MFA). Feito aqui só para a demo andar sozinha."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(URL_CDP, slow_mo=250 if passo_a_passo else None)
        ctx = browser.contexts[0]
        page = next((p for p in ctx.pages if "login.elaw" in p.url), None) or ctx.new_page()
        if "login.elaw" not in page.url:
            page.goto(f"{URL_MOCK}/login.elaw")
        page.fill('[id$=":username"]', "operador")
        page.fill('[id$=":password"]', "demo123")
        with page.expect_navigation():
            page.click('[id$=":btnAcessar"]')
        if "homePage" not in page.url:
            sys.exit("O login de demonstração falhou.")
        browser.close()   # via CDP isto só DESCONECTA: a janela continua aberta e logada
    trocar_por_aba_limpa()
    print(f"{AMARELO}{NEGRITO}[humano]{FIM}{AMARELO} login feito pelo operador — no mundo real o robô nunca "
          f"digita senha (SSO/MFA corporativo).{FIM}", flush=True)


def trocar_por_aba_limpa() -> None:
    """Abre uma aba nova (já logada, pelos cookies) e fecha as outras, pela API HTTP do DevTools.

    Motivo: uma aba que OUTRO cliente Playwright dirigiu pode deixar de receber os cliques do mouse
    depois que esse cliente desconecta (visto nesta demo). No uso real isso não acontece: a aba em que
    o operador entra com SSO/MFA nunca foi dirigida por Playwright antes do robô."""
    import json
    antigas = [t for t in json.load(urllib.request.urlopen(f"{URL_CDP}/json/list")) if t["type"] == "page"]
    urllib.request.urlopen(urllib.request.Request(f"{URL_CDP}/json/new?{URL_MOCK}/homePage.elaw", method="PUT")).read()
    for t in antigas:
        urllib.request.urlopen(f"{URL_CDP}/json/close/{t['id']}").read()


# ------------------------------------------------------------------ robô
def rodar_robo(args: list[str], passo_a_passo: bool) -> int:
    env = {**os.environ, "CPJ_LOGIN": "robo.leitura", "CPJ_SENHA": "cpj-demo-123", "PYTHONIOENCODING": "utf-8"}
    cmd = [sys.executable, str(RAIZ / "robo" / "rpa_elaw.py"), "--cdp", URL_CDP]
    if passo_a_passo:
        cmd += ["--slow-mo", "350"]
    info(f"$ python robo/rpa_elaw.py {' '.join(args)}")
    return subprocess.run(cmd + args, env=env, cwd=RAIZ).returncode


def ultima_execucao(depois_de: float) -> Path | None:
    pastas = [p for p in SAIDA.glob("*") if p.is_dir() and p.stat().st_mtime >= depois_de - 1]
    return max(pastas, key=lambda p: p.stat().st_mtime) if pastas else None


GRUPOS = {
    "concluídas pelo robô": ({"concluida", "concluida_ja_anexada", "reagendada"}, VERDE),
    "já concluídas por outra pessoa": ({"ja_concluida"}, VERDE),
    "aguardando (o robô tenta de novo amanhã)": ({"aguardando_peca", "aguardando_resultado", "cpj_sem_resposta"}, AMARELO),
}


def planilha_da_rodada(arq: Path) -> tuple[list, list]:
    """Linhas das abas 'Precisa de você' e 'Feito pelo robô' (sem a linha de aviso de aba vazia)."""
    try:
        from openpyxl import load_workbook
        wb = load_workbook(arq, read_only=True)
        abas = [[ln for ln in wb[nome].iter_rows(min_row=2, values_only=True) if ln[1] is not None]
                for nome in ("Precisa de você", "Feito pelo robô")]
        wb.close()
        return abas[0], abas[1]
    except Exception:
        return [], []


def mostrar_resumo(pasta: Path) -> None:
    with open(pasta / "resultado.csv", encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    cont = Counter(l["situacao"] for l in linhas)
    titulo("RESUMO DA EXECUÇÃO")
    for rotulo, (situacoes, cor) in GRUPOS.items():
        n = sum(cont[s] for s in situacoes)
        print(f"  {cor}{n:>3}{FIM}  {rotulo}")
    print(f"  {CINZA}detalhe por situação: {dict(cont)}{FIM}")
    voce, feitas = planilha_da_rodada(pasta / "PRECISA DE VOCE.xlsx")
    print(f"\n  {VERDE}{len(feitas):>3}{FIM}  linhas na aba 'Feito pelo robô' (o que o robô gravou no eLaw)")
    print(f"\n  {VERMELHO}{NEGRITO}{len(voce):>3}  PRECISAM DE VOCÊ{FIM}  (aba 'Precisa de você', em português):")
    for numero, tarefa, fila, o_que_fazer, *_ in voce:
        print(f"       {VERMELHO}•{FIM} {numero} (tarefa {tarefa}, {fila}): {o_que_fazer}")
    print(f"\n  Arquivos: {pasta}")
    for nome in ("plano.csv", "resultado.csv", "auditoria.jsonl", "log.txt", "PRECISA DE VOCE.xlsx"):
        if (pasta / nome).exists():
            print(f"    {CINZA}- {nome}{FIM}")


# ------------------------------------------------------------------ roteiro
def main() -> int:
    ap = argparse.ArgumentParser(description="Demonstração ponta a ponta do robô (mock local, dados fictícios)")
    ap.add_argument("--headless", action="store_true", help="Chrome sem janela")
    ap.add_argument("--passo-a-passo", action="store_true", help="robô em câmera lenta (para assistir)")
    ap.add_argument("--sem-cenario-sessao", action="store_true", help="pula o cenário de sessão expirada")
    args = ap.parse_args()
    checar_dependencias()

    titulo("1/5  Subindo o mock (eLaw + CPJ fictícios)")
    servidor = subir_mock()
    info(f"mock no ar em {URL_MOCK}  ·  cenários: {URL_MOCK}/__mock/cenarios  ·  API: {URL_MOCK}/cpj/docs")

    exe = achar_chrome()
    if exe is None:
        sys.exit("Não encontrei o Google Chrome nem o Chromium do Playwright. Instale o Chrome ou rode: "
                 "python -m playwright install chromium")
    perfil = Path(tempfile.mkdtemp(prefix="rpa-elaw-demo-"))
    titulo("2/5  Abrindo um Chrome isolado (perfil temporário, porta 9322)")
    info(f"{exe}")
    chrome = abrir_chrome(exe, perfil, args.headless)
    codigos: dict[str, int] = {}
    try:
        login_humano(args.passo_a_passo)

        titulo("3/5  Robô em DRY-RUN: relatório -> CPJ -> regras -> plano (nada é alterado)")
        t0 = time.time()
        codigos["dry-run"] = rodar_robo(["orquestrar", "--novo-relatorio"], args.passo_a_passo)

        titulo("4/5  Robô com --executar: conclui as tarefas prontas no eLaw")
        t1 = time.time()
        codigos["executar"] = rodar_robo(["orquestrar", "--executar"], args.passo_a_passo)
        pasta = ultima_execucao(t1)

        if not args.sem_cenario_sessao:
            titulo("5/5  Cenário extra: a sessão expira -> o robô PARA (código 2) e não tenta logar")
            urllib.request.urlopen(urllib.request.Request(f"{URL_MOCK}/__mock/expirar-sessoes", method="POST"))
            info("sessões do mock encerradas (simula o SSO derrubando a sessão)")
            codigos["sessao-expirada"] = rodar_robo(["buscar", "--numero", "0000000-00.0000.0.00.0000"],
                                                    args.passo_a_passo)
            esperado = codigos["sessao-expirada"] == 2
            print(f"  {VERDE if esperado else VERMELHO}código de saída = {codigos['sessao-expirada']} "
                  f"({'esperado' if esperado else 'INESPERADO'}){FIM}")
        if pasta and (pasta / "resultado.csv").exists():
            mostrar_resumo(pasta)
        print(f"\n  {CINZA}tempo total: {time.time() - t0:.0f} s · códigos de saída: {codigos}{FIM}")
    finally:
        fechar_chrome(chrome, perfil)
        servidor.should_exit = True
        info("Chrome da demo fechado e mock encerrado.")
    ok = codigos.get("dry-run") == 0 and codigos.get("executar") == 0 and codigos.get("sessao-expirada", 2) == 2
    print(f"\n{VERDE if ok else VERMELHO}{NEGRITO}{'DEMO OK' if ok else 'DEMO COM FALHAS'}{FIM}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
