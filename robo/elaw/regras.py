"""
Regras de negócio do robô — módulo PURO (sem navegador, sem rede): recebe os dados já
lidos do CPJ e devolve a decisão. É aqui que mora o "o que fazer com cada tarefa".

Fila CONTESTAÇÃO (tarefa "Anexar contestação" pendente no eLaw):
  1. processo não está no CPJ (no grupo de trabalho do cliente)     -> nao_achado_cpj
  2. tarefa "Anexar contestação no eLaw" concluída no CPJ            -> pronta / concluir_ja_anexada
  3. "Pauta - Contestação" ainda não concluída                       -> aguardando_peca
  4. pauta concluída + PDF de contestação deste processo             -> pronta / anexar
  5. pauta concluída sem PDF utilizável                              -> pauta_sem_pdf (precisa de você)
  + sem peça há N dias corridos desde a entrada da tarefa            -> pronta / reagendar

Fila AUDIÊNCIA (tarefa "Confirmar realização de audiência / Anexar Ata"):
  linha "AUDIENCIA: [REALIZADA -] FRUTIFERA|INFRUTIFERA" numa tarefa do CPJ lançada a partir
  da data de registro da tarefa no eLaw (trava contra resultado de audiência antiga)
  + ata = PDF anexado àquela tarefa (ou, na falta, o PDF com o nome padrão de ata)
                                                                     -> pronta / concluir_audiencia
  senão                                                              -> aguardando_resultado
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

from . import cnj
from .texto import norm, sem_acento

# ---- situações do PLANO ----
PRONTA = "pronta"
AGUARDANDO_PECA = "aguardando_peca"          # CPJ: Pauta - Contestação ainda não concluída
PAUTA_SEM_PDF = "pauta_sem_pdf"              # CPJ: pauta concluída, mas sem PDF de contestação utilizável
CPJ_NAO_ACHADO = "nao_achado_cpj"            # o nº não existe no CPJ (no grupo de trabalho do cliente)
CPJ_SEM_RESPOSTA = "cpj_sem_resposta"        # a API falhou (passageiro) -> volta na próxima rodada
AGUARDANDO_RESULTADO = "aguardando_resultado"  # audiência sem a linha de resultado no CPJ
SEM_NUMERO = "sem_numero"
DUPLICADA = "duplicada"
# ---- situações da EXECUÇÃO ----
CONCLUIDA = "concluida"
CONCLUIDA_JA_ANEXADA = "concluida_ja_anexada"
REAGENDADA = "reagendada"
JA_CONCLUIDA = "ja_concluida"                # alguém concluiu antes do robô (visto na re-checagem)
JA_ANEXADO = "ja_anexado"                    # já existe anexo com o mesmo nome e o modo é "sinalizar"
NAO_CONCLUIU = "nao_concluiu"                # Confirmar não pegou e a re-checagem diz "pendente"
ERRO = "erro"
NAO_EXECUTADA = "nao_executada"              # fora do --limite ou lote abortado

# ---- ações (quando PRONTA) ----
ANEXAR = "anexar"
CONCLUIR_JA_ANEXADA = "concluir_ja_anexada"
REAGENDAR = "reagendar"
CONCLUIR_AUDIENCIA = "concluir_audiencia"

SEM_CONTESTACAO = (AGUARDANDO_PECA, PAUTA_SEM_PDF, CPJ_NAO_ACHADO)
AGUARDANDO = (AGUARDANDO_PECA, AGUARDANDO_RESULTADO, CPJ_SEM_RESPOSTA)
CONCLUIDAS = (CONCLUIDA, CONCLUIDA_JA_ANEXADA, REAGENDADA, JA_CONCLUIDA)


@dataclass(frozen=True)
class EventosCPJ:
    """Nomes dos eventos (tarefas) que a equipe lança no CPJ."""
    pauta: str = "Pauta - Contestação"
    anexada: str = "Anexar contestação no eLaw"


@dataclass
class Avaliacao:
    situacao: str
    acao: str = ""
    detalhe: str = ""
    pj: int | None = None
    doc: dict | None = None          # documento do CPJ a baixar (contestação ou ata)
    resultado: str = ""              # audiência: Frutífera | Infrutífera
    antes: str = ""                  # reagendamento: a situação que levou a reagendar
    extra: dict = field(default_factory=dict)


# ------------------------------------------------------------------ utilidades
def rotulo(valor) -> str:
    """A API devolve alguns campos como {'label': ...}."""
    return (valor.get("label") if isinstance(valor, dict) else valor) or ""


def nome_doc(doc: dict) -> str:
    """O `path` às vezes vem com o caminho de rede inteiro (N:\\Setor\\...\\arquivo.pdf)."""
    return re.split(r"[\\/]", doc.get("path") or doc.get("nome") or "")[-1]


def _data_iso(texto) -> str:
    return str(texto or "")[:10]


def _mais_recente(docs: list[dict]) -> list[dict]:
    return sorted(docs, key=lambda d: (_data_iso(d.get("data_criacao")), d.get("id_ged") or 0), reverse=True)


def concluida(situacao: str) -> bool:
    return norm(situacao).startswith("conclu")


def situacao_evento(tramitacoes: list[dict], prefixo: str) -> str:
    """Situação do lançamento MAIS RECENTE cujo evento começa com `prefixo` ('' se não existe)."""
    sel = [t for t in tramitacoes if norm(rotulo(t.get("evento_desc"))).startswith(norm(prefixo))]
    sel.sort(key=lambda t: str(t.get("data_hora_lan") or ""))
    return rotulo(sel[-1].get("situacao_desc")) if sel else ""


# ------------------------------------------------------------------ contestação
# "Contestação - X.pdf", "SP - Contestação ...", "1. contestação ..." (comparado sem acento/caixa)
_RE_CONTESTACAO = re.compile(r"^(\d+\s*\.\s*)?([a-z]{2}\s*-\s*)?contestac")
_RE_NAO_PECA = re.compile(r"^(\d+_)?(email|e-mail|chat)\b")


def e_contestacao(nome: str) -> bool:
    """PDF cujo nome começa como contestação; e-mails, chats e .docx não são a peça."""
    n = _norm_nome(nome)
    return n.endswith(".pdf") and not _RE_NAO_PECA.match(n) and bool(_RE_CONTESTACAO.match(n))


def _norm_nome(nome: str) -> str:
    """Como norm(), mas preservando pontos e dois-pontos (extensão, 'AUDIENCIA:')."""
    return " ".join(sem_acento(nome).lower().split())


def de_outro_processo(nome: str, numero: str) -> bool:
    """TRAVA: o nome do arquivo traz o nº de OUTRO processo (peça anexada no cadastro errado)."""
    outro = cnj.extrair(nome)
    return bool(outro and numero) and not cnj.mesmo_processo(outro, numero)


def escolher_contestacao(docs: list[dict], numero: str = "") -> dict | None:
    """A contestação mais recente deste processo (ignora peças com nº de outro processo)."""
    cand = [d for d in docs if e_contestacao(nome_doc(d)) and not de_outro_processo(nome_doc(d), numero)]
    return (_mais_recente(cand) or [None])[0]


def avaliar_contestacao(pj: int | None, tramitacoes: list[dict], documentos: list[dict] | Callable[[], list[dict]],
                        numero: str, eventos: EventosCPJ = EventosCPJ()) -> Avaliacao:
    """Decide a fila de contestação. `documentos` pode ser uma função (só é consultada se precisar)."""
    if pj is None:
        return Avaliacao(CPJ_NAO_ACHADO, detalhe="processo não encontrado no CPJ (grupo de trabalho do cliente)")
    if concluida(situacao_evento(tramitacoes, eventos.anexada)):
        return Avaliacao(PRONTA, CONCLUIR_JA_ANEXADA, f"CPJ: '{eventos.anexada}' concluída", pj)
    pauta = situacao_evento(tramitacoes, eventos.pauta)
    if not concluida(pauta):
        return Avaliacao(AGUARDANDO_PECA, detalhe=f"CPJ: {eventos.pauta} {pauta.lower() or 'inexistente'}", pj=pj)
    docs = documentos() if callable(documentos) else documentos
    doc = escolher_contestacao(docs, numero)
    if doc is not None:
        return Avaliacao(PRONTA, ANEXAR, f"CPJ: {nome_doc(doc)}", pj, doc)
    errados = [nome_doc(d) for d in docs if e_contestacao(nome_doc(d)) and de_outro_processo(nome_doc(d), numero)]
    if errados:
        return Avaliacao(PAUTA_SEM_PDF, detalhe=f"CPJ: a contestação anexada é de OUTRO processo (não usada): "
                                                f"{errados[0]}", pj=pj)
    return Avaliacao(PAUTA_SEM_PDF, detalhe=f"CPJ: {eventos.pauta} concluída, mas sem PDF de contestação", pj=pj)


def dias_desde(data: str | date | None, hoje: date | None = None) -> int | None:
    """Dias corridos desde 'dd/mm/aaaa' (ou date). None se não der para ler."""
    if isinstance(data, datetime):
        data = data.date()
    if not isinstance(data, date):
        m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(data or ""))
        if not m:
            return None
        data = date(int(m[3]), int(m[2]), int(m[1]))
    return ((hoje or date.today()) - data).days


def aplicar_reagendamento(av: Avaliacao, data_registro: str | date | None, apos_dias: int,
                          hoje: date | None = None) -> Avaliacao:
    """Sem contestação há `apos_dias` dias corridos desde a ENTRADA da tarefa -> reagendar:
    concluir com 'Anexar defesa? = Não' + 'Prazo de contestação em curso' (o eLaw abre uma
    tarefa nova, com prazo novo). Contar antes do prazo do eLaw evita que fim de semana deixe passar."""
    if apos_dias <= 0 or av.situacao not in SEM_CONTESTACAO:
        return av
    d = dias_desde(data_registro, hoje)
    if d is None or d < apos_dias:
        return av
    return Avaliacao(PRONTA, REAGENDAR, f"{d} dias desde a entrada, sem contestação no CPJ ({av.detalhe})",
                     av.pj, antes=av.situacao)


# ------------------------------------------------------------------ audiência
_RE_AUDIENCIA = re.compile(r"audiencia\s*:\s*(?:realizada\s*-\s*)?(infrutifera|frutifera)\b")
_RE_ATA = re.compile(r"^ata de audiencia\s*-\s*(com|sem) acordo\b.*\.pdf$")
TIPO_ATA = {"Frutífera": "com", "Infrutífera": "sem"}


def resultado_audiencia(tramitacoes: list[dict], desde: str = "") -> tuple[str, dict] | None:
    """(resultado, tarefa) da linha padrão MAIS RECENTE lançada a partir de `desde` (AAAA-MM-DD).
    Um resultado anterior à tarefa do eLaw é de outra audiência -> ignorado (trava)."""
    for t in sorted(tramitacoes, key=lambda t: str(t.get("data_hora_lan") or ""), reverse=True):
        if desde and _data_iso(t.get("data_hora_lan")) < desde:
            break
        m = _RE_AUDIENCIA.search(_norm_nome(t.get("texto") or ""))
        if m:
            return ("Frutífera" if m.group(1) == "frutifera" else "Infrutífera"), t
    return None


def escolher_ata(docs: list[dict]) -> dict | None:
    """Ata mais recente com o nome padrão 'Ata de audiencia - com|sem acordo - ....pdf'."""
    return (_mais_recente([d for d in docs if _RE_ATA.match(_norm_nome(nome_doc(d)))]) or [None])[0]


def avaliar_audiencia(pj: int | None, tramitacoes: list[dict], docs_da_tarefa: Callable[[int], list[dict]],
                      docs_do_processo: Callable[[], list[dict]], desde: str = "") -> Avaliacao:
    """`desde` = data de registro da tarefa no eLaw (AAAA-MM-DD)."""
    if pj is None:
        return Avaliacao(CPJ_NAO_ACHADO, detalhe="processo não encontrado no CPJ (grupo de trabalho do cliente)")
    achado = resultado_audiencia(tramitacoes, desde)
    if achado is None:
        return Avaliacao(AGUARDANDO_RESULTADO, pj=pj,
                         detalhe="CPJ: sem a linha 'AUDIENCIA: FRUTIFERA|INFRUTIFERA' desde a entrada da tarefa")
    resultado, tarefa = achado
    pdfs = [d for d in docs_da_tarefa(tarefa["id_tramitacao"]) if nome_doc(d).lower().endswith(".pdf")]
    ata = (_mais_recente(pdfs) or [None])[0] or escolher_ata(docs_do_processo())
    evento = rotulo(tarefa.get("evento_desc"))
    detalhe = (f"CPJ: {resultado} ({evento}, {_data_iso(tarefa.get('data_hora_lan'))})"
               + (f"; ata: {nome_doc(ata)}" if ata else "; sem ata"))
    return Avaliacao(PRONTA, CONCLUIR_AUDIENCIA, detalhe, pj, ata, resultado)


# ------------------------------------------------------------------ "PRECISA DE VOCÊ"
def reagendada_com_problema(situacao: str, antes: str) -> bool:
    """Reagendada, mas o motivo pede correção no CPJ -> também vai para a lista do operador."""
    return situacao in (REAGENDADA, PRONTA) and antes in (PAUTA_SEM_PDF, CPJ_NAO_ACHADO)


def precisa_de_voce(situacao: str, acao: str = "", antes: str = "") -> bool:
    if reagendada_com_problema(situacao, antes) and (situacao == REAGENDADA or acao == REAGENDAR):
        return True
    return situacao not in (PRONTA, *AGUARDANDO, *CONCLUIDAS, DUPLICADA)


def o_que_fazer(situacao: str, detalhe: str = "", anexo: str = "", antes: str = "", acao: str = "") -> str:
    """Frase curta, em português simples, do que o operador precisa fazer."""
    if reagendada_com_problema(situacao, antes) and (situacao == REAGENDADA or acao == REAGENDAR):
        return "A tarefa foi (ou será) reagendada, mas corrija no CPJ: " + o_que_fazer(antes, detalhe)
    if situacao == PAUTA_SEM_PDF and "OUTRO processo" in detalhe:
        return ("A contestação anexada no CPJ é de outro processo (veja o detalhe). Corrija o cadastro no CPJ "
                "ou conclua a tarefa à mão.")
    if situacao == PAUTA_SEM_PDF:
        return ("No CPJ a 'Pauta - Contestação' está concluída, mas não há PDF com o nome 'Contestação - ...'. "
                "Anexe a peça no CPJ com esse padrão de nome ou conclua à mão.")
    if situacao == CPJ_NAO_ACHADO:
        return "O processo não foi encontrado no CPJ no grupo de trabalho do cliente. Confira o número e o cadastro."
    if situacao in (ERRO, NAO_CONCLUIU) and "ÓRFÃO" in detalhe:
        return (f"O PDF subiu (anexo {anexo}), mas a tarefa não foi concluída. Exclua esse anexo no processo e "
                "rode o robô de novo (ou conclua à mão).")
    if situacao in (ERRO, NAO_CONCLUIU):
        return "O robô não conseguiu concluir. Conclua à mão no eLaw ou rode de novo mais tarde."
    if situacao == JA_ANEXADO:
        return "O processo já tem um arquivo com esse nome. Confira e conclua a tarefa à mão."
    if situacao == NAO_EXECUTADA:
        return "O robô parou antes desta tarefa. Rode de novo."
    if situacao == SEM_NUMERO:
        return "A tarefa veio sem número de processo no relatório. Confira-a no eLaw."
    return "Confira esta tarefa no eLaw."
