"""
Gera `mock/dados.json`: a massa de dados 100% FICTÍCIA do mock (eLaw + CPJ).

Determinística (random.Random(42)): rodar de novo produz o mesmo arquivo. As datas
são guardadas como "dias atrás" e resolvidas quando o mock sobe, então o cenário
continua válido em qualquer dia (a janela de 90 dias, o reagendamento após 17 dias
e a trava da audiência dependem de datas relativas).

Cada processo representa UM cenário das regras de negócio — ver CENARIOS abaixo.

    python mock/seed.py
"""
from __future__ import annotations
import json
import random
from pathlib import Path

ARQUIVO = Path(__file__).with_name("dados.json")

GT_CLIENTE = 700          # grupo de trabalho do cliente no CPJ (fictício)
GT_OUTRO = 800            # outro cliente do escritório com processo de MESMO nº
TIPO_CONTESTACAO = "7101"
TIPO_AUDIENCIA = "7102"
TIPO_PROCURACAO = "7103"
TIPO_DILIGENCIA = "7104"

UF_POR_TR = {"26": "SP", "21": "RS", "16": "PR", "24": "SC", "13": "MG"}

NOMES = [
    "Ana Exemplo Ficticia", "Bruno Teste Demonstrativo", "Carla Simulada Souza", "Daniel Mock Pereira",
    "Elisa Inventada Rocha", "Fábio Hipotético Lima", "Gina Amostra Costa", "Heitor Protótipo Alves",
    "Íris Modelo Ribeiro", "João Ensaio Martins", "Kátia Rascunho Dias", "Leandro Esboço Gomes",
    "Mirela Piloto Nunes", "Nestor Cenário Barros", "Olga Sandbox Freitas", "Paulo Placeholder Teixeira",
    "Renata Fixture Moraes", "Rui Stub Cardoso", "Sara Dummy Mendes", "Túlio Seed Araújo",
    "Úrsula Faker Pinto", "Vítor Dado Correia",
]
RESPONSAVEIS = ["Advogado Demo 1", "Advogada Demo 2", "Advogado Demo 3"]



def digitos_verificadores(sequencial: str, ano: str, j: str, tr: str, origem: str) -> str:
    """DV do nº CNJ (Resolução CNJ 65/2008, ISO 7064 mod 97-10). Cópia independente da
    função do robô: o mock é um 'sistema externo' e não importa nada de robo/."""
    resto = int(f"{sequencial}{ano}{j}{tr}{origem}00") % 97
    return f"{98 - resto:02d}"


class Gerador:
    def __init__(self, seed: int = 42):
        self.rng = random.Random(seed)
        self.usados: set[str] = set()

    def _limpo(self, s: str) -> bool:
        return s not in self.usados

    def numero(self, faixa: tuple[int, int]) -> int:
        while True:
            n = self.rng.randint(*faixa)
            if self._limpo(str(n)):
                self.usados.add(str(n))
                return n

    def cnj(self) -> str:
        while True:
            seq = f"{self.rng.randint(9_000_000, 9_999_999):07d}"
            tr = self.rng.choice(sorted(UF_POR_TR))
            origem = f"{self.rng.randint(1, 9999):04d}"
            dv = digitos_verificadores(seq, "2026", "8", tr, origem)
            cnj = f"{seq}-{dv}.2026.8.{tr}.{origem}"
            if self._limpo(cnj) and self._limpo(cnj.replace("-", "").replace(".", "")):
                self.usados.add(cnj)
                return cnj


# ---------------------------------------------------------------------------------------------
# Cenários: cada um vira um processo no eLaw (com a tarefa) e, quase sempre, um cadastro no CPJ.
#   registrado: dias desde a entrada da tarefa no eLaw (prazo do eLaw = entrada + 20 dias)
#   tram: tarefas/andamentos no CPJ -> (evento, situação, dias atrás, texto, [docs da tarefa])
#   docs: documentos do processo no CPJ -> (nome, dias atrás)
# ---------------------------------------------------------------------------------------------
PAUTA, ANEXADA, ATA = "Pauta - Contestação", "Anexar contestação no eLaw", "Secretaria - Envio de Ata"
OK, PEND = "Concluída", "Pendente"

CENARIOS: list[dict] = [
    dict(cod="contestacao_pronta", tipo=TIPO_CONTESTACAO, registrado=4,
         esperado="pronta -> anexa o PDF e conclui",
         tram=[(PAUTA, OK, 2, "", [])], docs=[("Contestação - {cnj}.pdf", 2)]),
    dict(cod="contestacao_pronta_prefixo_uf", tipo=TIPO_CONTESTACAO, registrado=6,
         esperado="pronta ('UF - Contestação'); e-mail e procuração ignorados",
         tram=[(PAUTA, OK, 1, "", [])],
         docs=[("{uf} - Contestação - {cnj}.pdf", 1), ("email_cliente_subsidios.pdf", 3), ("Procuração.pdf", 9)]),
    dict(cod="contestacao_pronta_numerada", tipo=TIPO_CONTESTACAO, registrado=3,
         esperado="pronta ('1. contestação'); .docx, chat e versão antiga ignorados",
         tram=[(PAUTA, OK, 1, "", [])],
         docs=[("1. contestação {cnj}.pdf", 1), ("Contestação - rascunho.docx", 2),
               ("chat_atendimento_contestacao.pdf", 2), ("Contestação - versão antiga.pdf", 6)]),
    dict(cod="contestacao_ja_anexada", tipo=TIPO_CONTESTACAO, registrado=8,
         esperado="concluir_ja_anexada (CPJ: 'Anexar contestação no eLaw' concluída)",
         tram=[(PAUTA, OK, 5, "", []), (ANEXADA, OK, 2, "", [])], docs=[("Contestação - {cnj}.pdf", 5)]),
    dict(cod="contestacao_aguardando", tipo=TIPO_CONTESTACAO, registrado=3,
         esperado="aguardando_peca (Pauta ainda pendente)",
         tram=[(PAUTA, PEND, 3, "", [])], docs=[]),
    dict(cod="contestacao_pauta_sem_pdf", tipo=TIPO_CONTESTACAO, registrado=5,
         esperado="pauta_sem_pdf -> PRECISA DE VOCÊ",
         tram=[(PAUTA, OK, 1, "", [])], docs=[("email_cliente.pdf", 2), ("Contestação - {cnj}.docx", 1)]),
    dict(cod="contestacao_pdf_de_outro_processo", tipo=TIPO_CONTESTACAO, registrado=7,
         esperado="pauta_sem_pdf (TRAVA: o PDF traz o nº de OUTRO processo) -> PRECISA DE VOCÊ",
         tram=[(PAUTA, OK, 2, "", [])], docs=[("Contestação - (Processo nº {outro}).pdf", 2)]),
    dict(cod="contestacao_reagendar", tipo=TIPO_CONTESTACAO, registrado=18,
         esperado="reagendar (18 dias sem peça; o eLaw cria tarefa nova)",
         tram=[(PAUTA, PEND, 18, "", [])], docs=[]),
    dict(cod="contestacao_reagendar_sem_pdf", tipo=TIPO_CONTESTACAO, registrado=19,
         esperado="reagendar + PRECISA DE VOCÊ (pauta concluída sem PDF)",
         tram=[(PAUTA, OK, 4, "", [])], docs=[]),
    dict(cod="contestacao_dois_clientes", tipo=TIPO_CONTESTACAO, registrado=5,
         esperado="pronta: o MESMO nº existe no CPJ para outro cliente; só o grupo de trabalho certo vale",
         tram=[(PAUTA, OK, 1, "", [])], docs=[("Contestação - {cnj}.pdf", 1)],
         outro_cliente=dict(tram=[(ANEXADA, OK, 30, "", [])], docs=[("Contestação - {cnj}.pdf", 31)])),
    dict(cod="contestacao_nao_achada_cpj", tipo=TIPO_CONTESTACAO, registrado=2,
         esperado="nao_achado_cpj -> PRECISA DE VOCÊ", cpj=False),
    dict(cod="contestacao_anexo_orfao", tipo=TIPO_CONTESTACAO, registrado=6,
         esperado="o processo já tem o arquivo (órfão de tentativa anterior) -> não reenvia; conclui 'Já anexada'",
         tram=[(PAUTA, OK, 2, "", [])], docs=[("Contestação - {cnj}.pdf", 2)],
         anexos_elaw=[("Contestacao - {cnj}.pdf", "", 1, False)]),
    dict(cod="contestacao_concluida_por_outra_pessoa", tipo=TIPO_CONTESTACAO, registrado=9,
         esperado="pronta no plano, mas alguém conclui antes -> re-checagem por ID = ja_concluida",
         tram=[(PAUTA, OK, 3, "", [])], docs=[("Contestação - {cnj}.pdf", 3)],
         concluir_ao_gerar_relatorio=True),
    dict(cod="contestacao_falha_no_elaw", tipo=TIPO_CONTESTACAO, registrado=5,
         esperado="o upload grava, o Confirmar falha -> nao_concluiu + ANEXO ÓRFÃO -> PRECISA DE VOCÊ",
         tram=[(PAUTA, OK, 1, "", [])], docs=[("Contestação - {cnj}.pdf", 1)],
         falhar_confirmacao=True),
    dict(cod="audiencia_frutifera", tipo=TIPO_AUDIENCIA, registrado=6,
         esperado="concluir audiência: Frutífera + ata (com acordo)",
         tram=[(ATA, OK, 2, "Audiência realizada por videoconferência.\nAUDIENCIA: REALIZADA - FRUTIFERA\n"
                             "Acordo homologado.", [("Ata AUD - {cnj}.pdf", 2)])], docs=[]),
    dict(cod="audiencia_infrutifera", tipo=TIPO_AUDIENCIA, registrado=5,
         esperado="concluir audiência: Infrutífera + ata (sem acordo)",
         tram=[(ATA, OK, 1, "AUDIENCIA: INFRUTIFERA", [("({cnj}) Ata AUD.pdf", 1)])], docs=[]),
    dict(cod="audiencia_resultado_antigo", tipo=TIPO_AUDIENCIA, registrado=10,
         esperado="aguardando_resultado (TRAVA: o único resultado é ANTERIOR à tarefa)",
         tram=[(ATA, OK, 40, "AUDIENCIA: REALIZADA - INFRUTIFERA", [("Ata AUD antiga.pdf", 40)])], docs=[]),
    dict(cod="audiencia_sem_resultado", tipo=TIPO_AUDIENCIA, registrado=4,
         esperado="aguardando_resultado (sem a linha AUDIENCIA: no CPJ)",
         tram=[(ATA, PEND, 1, "Aguardando a ata do tribunal.", [])], docs=[]),
    dict(cod="audiencia_ata_por_nome", tipo=TIPO_AUDIENCIA, registrado=7,
         esperado="concluir audiência: ata achada pelo nome padrão no processo (sem PDF na tarefa)",
         tram=[(ATA, OK, 1, "AUDIENCIA: FRUTIFERA", [])],
         docs=[("Ata de audiencia - com acordo - {cnj}.pdf", 1)]),
    dict(cod="outro_tipo_de_tarefa", tipo=TIPO_PROCURACAO, registrado=3,
         esperado="ignorada (tipo de tarefa fora do escopo do robô)", cpj=False),
    dict(cod="fora_da_janela_de_90_dias", tipo=TIPO_CONTESTACAO, registrado=120,
         esperado="fora do relatório (entrou há mais de 90 dias)",
         tram=[(PAUTA, PEND, 120, "", [])], docs=[]),
]


def _dt(g: Gerador) -> str:
    return f"{g.rng.randint(8, 18):02d}:{g.rng.choice((0, 15, 30, 45)):02d}:00"


def gerar() -> dict:
    g = Gerador(42)
    cnjs = [g.cnj() for _ in CENARIOS]
    nomes = g.rng.sample(NOMES, len(CENARIOS))
    processos, cpj_proc, cpj_tram, cpj_docs = [], [], [], []

    def add_cpj(pj: int, cnj: str, gt: int, tram: list, docs: list, fmt: dict) -> None:
        cpj_proc.append({"pj": pj, "numero_processo": cnj, "incidente": 0, "grupo_trabalho": gt,
                         "grupo_desc": "Cível - Cliente Exemplo" if gt == GT_CLIENTE else "Cível - Outro Cliente"})
        for evento, situacao, dias, texto, docs_t in tram:
            id_tram = g.numero((9_100_000, 9_899_999))
            cpj_tram.append({"id_tramitacao": id_tram, "pj": pj, "evento": evento, "situacao": situacao,
                             "dias_atras": dias, "hora": _dt(g), "texto": texto})
            for nome, d in docs_t:
                cpj_docs.append({"id_ged": g.numero((3_100_000, 3_899_999)), "pj": pj,
                                 "nome": nome.format(**fmt), "dias_atras": d, "id_tramitacao": id_tram})
        for nome, d in docs:
            cpj_docs.append({"id_ged": g.numero((3_100_000, 3_899_999)), "pj": pj,
                             "nome": nome.format(**fmt), "dias_atras": d, "id_tramitacao": None})

    for i, (cen, cnj, parte) in enumerate(zip(CENARIOS, cnjs, nomes)):
        uf = UF_POR_TR[cnj.split(".")[3]]
        fmt = {"cnj": cnj, "uf": uf, "outro": cnjs[1]}
        id_proc = g.numero((410_000, 419_999))
        tarefas = [{
            "id": g.numero((8_800_000, 8_899_999)), "tipo": cen["tipo"], "registrado_dias": cen["registrado"],
            "prazo_em_dias": 20, "responsavel": RESPONSAVEIS[i % 3],
            "descricao": "Tarefa gerada automaticamente pelo workflow (fictícia).",
            "concluir_ao_gerar_relatorio": cen.get("concluir_ao_gerar_relatorio", False),
            "falhar_confirmacao": cen.get("falhar_confirmacao", False),
        }]
        if i == 0:   # ruído: uma tarefa de outro tipo na mesma ficha
            tarefas.append({**tarefas[0], "id": g.numero((8_800_000, 8_899_999)), "tipo": TIPO_DILIGENCIA,
                            "registrado_dias": 2, "concluir_ao_gerar_relatorio": False})
        anexos = [{"id": g.numero((6_100_000, 6_899_999)), "nome": "Peticao inicial.pdf",
                   "tipo": "Petição Inicial", "dias_atras": cen["registrado"] + 2, "tarefa_id": None}]
        for nome, tipo, dias, vinc in cen.get("anexos_elaw", []):
            anexos.append({"id": g.numero((6_100_000, 6_899_999)), "nome": nome.format(**fmt), "tipo": tipo,
                           "dias_atras": dias, "tarefa_id": tarefas[0]["id"] if vinc else None})
        processos.append({
            "id": id_proc, "numero": cnj, "parte_contraria": parte, "empresa": "Banco Fictício S.A.",
            "escritorio": "Escritório Exemplo Advocacia", "area": "Cível", "uf": uf, "status": "Ativo",
            "cenario": cen["cod"], "esperado": cen["esperado"], "tarefas": tarefas, "anexos": anexos,
        })
        if cen.get("cpj", True):
            if "outro_cliente" in cen:   # cadastrado ANTES: sem o filtro de GT, o robô leria este
                oc = cen["outro_cliente"]
                add_cpj(g.numero((510_000, 599_999)), cnj, GT_OUTRO, oc["tram"], oc["docs"], fmt)
            add_cpj(g.numero((510_000, 599_999)), cnj, GT_CLIENTE, cen["tram"], cen["docs"], fmt)

    return {
        "_aviso": "Dados 100% fictícios gerados por mock/seed.py (random.Random(42)).",
        "usuario": {"login": "operador", "senha": "demo123", "nome": "Operador Demo"},
        "cpj_credenciais": {"login": "robo.leitura", "senha": "cpj-demo-123"},
        "grupo_trabalho_cliente": GT_CLIENTE,
        "tipos_tarefa": {
            TIPO_CONTESTACAO: "Anexar contestação",
            TIPO_AUDIENCIA: "Confirmar realização de audiência / Anexar Ata da Audiência",
            TIPO_PROCURACAO: "Juntar procuração",
            TIPO_DILIGENCIA: "Cumprir diligência",
        },
        "processos": processos,
        "cpj": {"processos": cpj_proc, "tramitacoes": cpj_tram, "documentos": cpj_docs},
    }


def main() -> None:
    dados = gerar()
    ARQUIVO.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ARQUIVO.name}: {len(dados['processos'])} processos, "
          f"{len(dados['cpj']['processos'])} cadastros no CPJ, {len(dados['cpj']['documentos'])} documentos.")


if __name__ == "__main__":
    main()
