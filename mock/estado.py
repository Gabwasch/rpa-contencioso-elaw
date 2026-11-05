"""
Estado em memória do mock (eLaw + CPJ). Carregado de `dados.json` a cada início do
servidor: tudo o que o robô faz (concluir tarefa, anexar, gerar relatório) vive só
enquanto o processo do mock estiver de pé.
"""
from __future__ import annotations
import json
import random
import secrets
import threading
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

DADOS = Path(__file__).with_name("dados.json")

STATUS_ROTULO = {"1": "Pendente", "4": "Atrasado", "2": "Concluído", "6": "Confirmado em atraso",
                 "3": "Cancelado", "7": "Em análise", "8": "A Vencer"}
STATUS_COR = {"1": "yellow", "4": "red", "2": "green", "6": "green", "3": "blue", "7": "purple", "8": "orange"}
STATUS_FILTRO = {"1": "Pendentes", "4": "Atrasados", "8": "A Vencer", "2": "Concluídos",
                 "6": "Confirmados em Atraso", "3": "Cancelados", "7": "Em análise"}

# Tipos de documento (fictícios) — o form de conclusão aceita poucos; o modal GED, vários.
TIPOS_DOC_CONCLUSAO = {"41": "Defesa", "42": "Contestação IA"}
TIPOS_ATA = {"51": "Ata de Audiência", "52": "Ata de audiência com acordo", "53": "Ata de audiência sem acordo"}
TIPOS_GED = {"31": "Contestação", "41": "Defesa", "33": "Petição", "34": "Procuração", "35": "Acordo protocolado",
             "36": "Comprovante", "51": "Ata de Audiência"}
TEMPLATES = {"901": "Acordo", "902": "Andamentos", "903": "Audiências", "904": "C01 - Relatório principal",
             "905": "Tarefas"}
JUSTIFICATIVAS = ["Adiamento da audiência", "Já anexada", "Prazo de contestação em curso", "Sem decisão do mérito"]


def sem_acento(texto: str) -> str:
    """O GED do eLaw grava o nome do arquivo sem acentos ('Contestação' -> 'Contestacao')."""
    t = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in t if not unicodedata.combining(c))


def br(d: date | datetime | None) -> str:
    if d is None:
        return ""
    return d.strftime("%d/%m/%Y %H:%M") if isinstance(d, datetime) else d.strftime("%d/%m/%Y")


def _jid(rng: random.Random) -> str:
    return f"j_id_{rng.randint(1, 9)}{rng.choice('abcdefghijklmnopqrstuvwxyz')}{rng.randint(0, 9)}"


class Estado:
    def __init__(self, arquivo: Path = DADOS, hoje: date | None = None, instavel: bool = True,
                 limite_token: int = 30, atraso_relatorio: tuple[float, float] = (3.0, 5.0)):
        d = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        self.lock = threading.RLock()
        self.hoje = hoje or date.today()
        self.usuario = d["usuario"]
        self.cpj_cred = d["cpj_credenciais"]
        self.tipos_tarefa: dict[str, str] = d["tipos_tarefa"]
        self.gt_cliente = d["grupo_trabalho_cliente"]
        self.instavel = instavel                # CPJ: 1 a cada 13 requisições responde 503 (testa o retry)
        self.limite_token = limite_token        # CPJ: o token "vence" após N usos (testa o re-login)
        self.atraso_relatorio = atraso_relatorio

        # prefixos j_id_* SORTEADOS a cada início: só seletor por sufixo de id funciona
        rng = random.SystemRandom()
        self.prefixos = {area: _jid(rng) for area in
                         ("login", "busca", "pauta", "ged", "confirm", "tarefas", "rel", "meus", "dlg", "topo")}
        self._rng = rng

        self.processos: dict[int, dict] = {}
        self.tarefas: dict[int, dict] = {}
        for p in d["processos"]:
            proc = {k: v for k, v in p.items() if k not in ("tarefas", "anexos")}
            proc["anexos"] = [{**a, "data": self._dias(a.pop("dias_atras")), "usuario": "importacao",
                               "tamanho": "48 KB"} for a in p["anexos"]]
            self.processos[proc["id"]] = proc
            for t in p["tarefas"]:
                self._nova_tarefa(proc["id"], t["tipo"], self._dias(t["registrado_dias"]), t["prazo_em_dias"],
                                  responsavel=t["responsavel"], descricao=t["descricao"], id_=t["id"],
                                  concluir_ao_gerar_relatorio=t["concluir_ao_gerar_relatorio"],
                                  falhar_confirmacao=t["falhar_confirmacao"])
        self.seq_anexo = max(a["id"] for p in self.processos.values() for a in p["anexos"]) + 1000
        self.seq_tarefa = max(self.tarefas) + 1000

        c = d["cpj"]
        self.cpj_processos = c["processos"]
        self.cpj_tram = [{**t, "data_hora_lan": f"{self._dias(t['dias_atras']).isoformat()} {t['hora']}"}
                         for t in c["tramitacoes"]]
        self.cpj_docs = {doc["id_ged"]: {**doc, "data_criacao": f"{self._dias(doc['dias_atras']).isoformat()} 10:00:00"}
                         for doc in c["documentos"]}
        self.cpj_tokens: dict[str, int] = {}
        self.cpj_contador = 0

        self.sessoes: dict[str, dict] = {}
        self.staging: dict[str, dict] = {}
        self.relatorios: dict[int, dict] = {}
        self.seq_relatorio = 7_340_000 + rng.randint(1, 999)
        ontem = datetime.combine(self.hoje - timedelta(days=1), datetime.min.time()) + timedelta(hours=9)
        for n, nome in enumerate(("Tarefas", "C01 - Relatório principal")):   # relatórios antigos da conta
            self._registrar_relatorio(nome, [], ontem + timedelta(minutes=40 * n), pronto=True)

    # ---------------------------------------------------------------- utilidades
    def _dias(self, dias_atras: int) -> date:
        return self.hoje - timedelta(days=int(dias_atras))

    def prefixo(self, area: str) -> str:
        return self.prefixos[area]

    def jid_aleatorio(self) -> str:
        """id auto-gerado que muda a CADA renderização (ex.: botão 'Novo Arquivo')."""
        return _jid(self._rng)

    def _nova_tarefa(self, proc_id: int, tipo: str, registrado: date, prazo_em_dias: int = 20, *,
                     responsavel: str = "Advogado Demo 1", descricao: str = "", id_: int | None = None,
                     anterior: int | None = None, concluir_ao_gerar_relatorio: bool = False,
                     falhar_confirmacao: bool = False) -> dict:
        t = {"id": id_ or self.proximo_id_tarefa(), "processo_id": proc_id, "tipo": tipo,
             "registrado": registrado, "prazo": registrado + timedelta(days=prazo_em_dias),
             "situacao": "aberta", "confirmado_em": None, "confirmado_por": "", "responsavel": responsavel,
             "descricao": descricao, "anterior": anterior, "detalhe_conclusao": "",
             "concluir_ao_gerar_relatorio": concluir_ao_gerar_relatorio,
             "falhar_confirmacao": falhar_confirmacao}
        self.tarefas[t["id"]] = t
        return t

    def proximo_id_tarefa(self) -> int:
        with self.lock:
            self.seq_tarefa += 7
            return self.seq_tarefa

    def proximo_id_anexo(self) -> int:
        with self.lock:
            self.seq_anexo += 3
            return self.seq_anexo

    def status_tarefa(self, t: dict) -> str:
        if t["situacao"] == "concluida":
            return "2" if t["confirmado_em"] <= t["prazo"] else "6"
        if t["situacao"] == "cancelada":
            return "3"
        return "4" if t["prazo"] < self.hoje else "1"

    def subtipo(self, t: dict) -> str:
        return self.tipos_tarefa.get(t["tipo"], t["tipo"])

    def tarefas_do_processo(self, proc_id: int) -> list[dict]:
        return sorted((t for t in self.tarefas.values() if t["processo_id"] == proc_id), key=lambda t: t["id"])

    def concluir_tarefa(self, t: dict, por: str, detalhe: str) -> None:
        t.update(situacao="concluida", confirmado_em=self.hoje, confirmado_por=por, detalhe_conclusao=detalhe)

    def novo_anexo(self, proc_id: int, nome: str, tipo: str, tamanho: int, tarefa_id: int | None = None) -> dict:
        a = {"id": self.proximo_id_anexo(), "nome": sem_acento(nome), "tipo": tipo, "data": self.hoje,
             "usuario": self.usuario["login"], "tamanho": f"{max(1, tamanho // 1024)} KB", "tarefa_id": tarefa_id}
        self.processos[proc_id]["anexos"].append(a)
        return a

    # ---------------------------------------------------------------- sessões (eLaw)
    def nova_sessao(self) -> str:
        sid = secrets.token_urlsafe(18)
        primeira = min(self.tarefas)
        self.sessoes[sid] = {
            "usuario": self.usuario["login"], "etoken": secrets.token_hex(8), "growl": [],
            "busca": {"tipo": "numero", "texto": "", "resultado": None},
            # a tela de tarefas RESTAURA a última pesquisa da conta (aqui: uma busca por ID, de
            # concluídos, feita "ontem") -> quem não clicar em "Limpar Pesquisa" leva isso junto
            "tarefas": {"tipo_pesquisa": "id", "texto": str(primeira), "tipo_data": "data", "status": ["2"],
                        "tipos": [], "inicio": br(self.hoje - timedelta(days=30)), "fim": br(self.hoje),
                        "resultado": None},
            # "Meus Relatórios" guarda o filtro de Data da sessão: abre com a data de ONTEM
            "meus": {"data": br(self.hoje - timedelta(days=1)), "status": "", "visivel": False},
        }
        return sid

    @staticmethod
    def filtros_tarefas_limpos(hoje: date) -> dict:
        return {"tipo_pesquisa": "geral", "texto": "", "tipo_data": "data", "status": [], "tipos": [],
                "inicio": br(hoje), "fim": br(hoje), "resultado": None}

    # ---------------------------------------------------------------- relatórios
    def _registrar_relatorio(self, nome: str, linhas: list[list], criado: datetime, pronto: bool = False,
                             filtros: str = "") -> dict:
        with self.lock:
            self.seq_relatorio += self._rng.randint(1, 4)
            rid = self.seq_relatorio
        atraso = 0 if pronto else self._rng.uniform(*self.atraso_relatorio)
        rel = {"id": rid, "nome": nome, "criado": criado, "pronto_em": time.time() + atraso,
               "linhas": linhas, "filtros": filtros, "usuario": self.usuario["login"]}
        if pronto:
            rel["pronto_em"] = 0
        self.relatorios[rid] = rel
        return rel

    def gerar_relatorio_tarefas(self, ids: list[int], template: str, filtros: str) -> dict:
        linhas = []
        for tid in ids:
            t = self.tarefas[tid]
            p = self.processos[t["processo_id"]]
            linhas.append([p["id"], p["numero"], t["id"], STATUS_ROTULO[self.status_tarefa(t)], "ALERTA",
                           self.subtipo(t), br(t["registrado"]), br(t["prazo"]), p["parte_contraria"],
                           t["responsavel"]])
        rel = self._registrar_relatorio(TEMPLATES.get(template, "Tarefas"), linhas, datetime.now(), filtros=filtros)
        # cenário "concluída por outra pessoa": alguém fecha a tarefa logo depois do relatório sair
        for tid in ids:
            t = self.tarefas[tid]
            if t["concluir_ao_gerar_relatorio"] and t["situacao"] == "aberta":
                t["concluir_ao_gerar_relatorio"] = False
                self.concluir_tarefa(t, "outra.pessoa", "Já anexada (concluída manualmente pela equipe)")
        return rel

    @staticmethod
    def relatorio_pronto(rel: dict) -> bool:
        return time.time() >= rel["pronto_em"]
