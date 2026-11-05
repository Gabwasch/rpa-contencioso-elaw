"""Cada desfecho das regras de negócio, com dados montados à mão (sem navegador, sem rede)."""
from datetime import date

import pytest

from elaw import cnj, regras as R

N = cnj.gerar(9_100_200, 2026, 8, 26, 100)
OUTRO = cnj.gerar(9_300_400, 2026, 8, 21, 200)
HOJE = date(2026, 3, 20)


def tram(evento, situacao, data="2026-03-10 10:00:00", texto="", id_=1):
    return {"id_tramitacao": id_, "evento_desc": {"label": evento}, "situacao_desc": {"label": situacao},
            "data_hora_lan": data, "texto": texto}


def doc(nome, data="2026-03-10 10:00:00", id_ged=10, caminho=None):
    return {"id_ged": id_ged, "path": caminho or nome, "data_criacao": data}


PAUTA_OK = tram("Pauta - Contestação", "Concluída")


# ------------------------------------------------------------------ contestação
def test_nao_achado_no_cpj():
    assert R.avaliar_contestacao(None, [], [], N).situacao == R.CPJ_NAO_ACHADO


def test_ja_anexada_no_cpj_conclui_sem_anexo():
    av = R.avaliar_contestacao(1, [PAUTA_OK, tram("Anexar contestação no eLaw", "Concluída")], [], N)
    assert (av.situacao, av.acao) == (R.PRONTA, R.CONCLUIR_JA_ANEXADA)


def test_pauta_pendente_aguarda_a_peca():
    av = R.avaliar_contestacao(1, [tram("Pauta - Contestação", "Pendente")], [], N)
    assert av.situacao == R.AGUARDANDO_PECA


def test_documentos_so_sao_buscados_quando_a_pauta_esta_concluida():
    def nao_chamar():
        raise AssertionError("não deveria buscar documentos")
    assert R.avaliar_contestacao(1, [], nao_chamar, N).situacao == R.AGUARDANDO_PECA


@pytest.mark.parametrize("nome", [f"Contestação - {N}.pdf", f"SP - Contestação - {N}.pdf",
                                  f"1. contestação {N}.pdf", "CONTESTACAO final.pdf"])
def test_pronta_quando_ha_pdf_de_contestacao(nome):
    av = R.avaliar_contestacao(1, [PAUTA_OK], [doc(nome)], N)
    assert (av.situacao, av.acao) == (R.PRONTA, R.ANEXAR)
    assert R.nome_doc(av.doc) == nome


@pytest.mark.parametrize("nome", ["email_cliente.pdf", "chat_contestacao.pdf", f"Contestação - {N}.docx",
                                  "Procuração.pdf", "e-mail contestação.pdf"])
def test_nao_e_a_peca(nome):
    assert not R.e_contestacao(nome)


def test_pauta_concluida_sem_pdf_precisa_de_voce():
    av = R.avaliar_contestacao(1, [PAUTA_OK], [doc("email_cliente.pdf"), doc(f"Contestação - {N}.docx")], N)
    assert av.situacao == R.PAUTA_SEM_PDF
    assert R.precisa_de_voce(av.situacao)


def test_trava_pdf_com_numero_de_outro_processo():
    av = R.avaliar_contestacao(1, [PAUTA_OK], [doc(f"Contestação - (Processo nº {OUTRO}).pdf")], N)
    assert av.situacao == R.PAUTA_SEM_PDF
    assert "OUTRO processo" in av.detalhe
    assert "outro processo" in R.o_que_fazer(av.situacao, av.detalhe)


def test_escolhe_a_contestacao_mais_recente_e_aceita_caminho_de_rede():
    docs = [doc("Contestação - antiga.pdf", "2026-03-01 09:00:00", 1),
            doc("x", "2026-03-12 09:00:00", 2, caminho="N:\\Contencioso\\Cliente\\Contestação - nova.pdf")]
    assert R.nome_doc(R.escolher_contestacao(docs, N)) == "Contestação - nova.pdf"


def test_usa_o_evento_mais_recente():
    t = [tram("Pauta - Contestação", "Concluída", "2026-03-01 10:00:00"),
         tram("Pauta - Contestação", "Pendente", "2026-03-15 10:00:00")]   # reaberta depois
    assert R.situacao_evento(t, "pauta - contestacao") == "Pendente"


# ------------------------------------------------------------------ reagendamento
def test_reagenda_apos_n_dias_corridos():
    av = R.Avaliacao(R.AGUARDANDO_PECA, detalhe="pauta pendente")
    r = R.aplicar_reagendamento(av, "02/03/2026", 17, HOJE)          # 18 dias
    assert (r.situacao, r.acao, r.antes) == (R.PRONTA, R.REAGENDAR, R.AGUARDANDO_PECA)


def test_nao_reagenda_antes_do_prazo_nem_desligado_nem_se_pronta():
    av = R.Avaliacao(R.AGUARDANDO_PECA)
    assert R.aplicar_reagendamento(av, "10/03/2026", 17, HOJE) is av   # 10 dias
    assert R.aplicar_reagendamento(av, "01/01/2026", 0, HOJE) is av    # 0 = desligado
    pronta = R.Avaliacao(R.PRONTA, R.ANEXAR)
    assert R.aplicar_reagendamento(pronta, "01/01/2026", 17, HOJE) is pronta


def test_reagendada_com_problema_no_cpj_tambem_vai_para_o_operador():
    r = R.aplicar_reagendamento(R.Avaliacao(R.PAUTA_SEM_PDF), "01/03/2026", 17, HOJE)
    assert R.precisa_de_voce(r.situacao, r.acao, r.antes)
    assert R.precisa_de_voce(R.REAGENDADA, R.REAGENDAR, R.PAUTA_SEM_PDF)
    assert not R.precisa_de_voce(R.REAGENDADA, R.REAGENDAR, R.AGUARDANDO_PECA)


def test_dias_desde():
    assert R.dias_desde("13/03/2026", HOJE) == 7
    assert R.dias_desde(date(2026, 3, 19), HOJE) == 1
    assert R.dias_desde("", HOJE) is None


# ------------------------------------------------------------------ audiência
def _avaliar_aud(trams, docs_tarefa=None, docs_proc=None, desde="2026-03-05"):
    return R.avaliar_audiencia(1, trams, lambda _id: docs_tarefa or [], lambda: docs_proc or [], desde)


@pytest.mark.parametrize("texto,esperado", [("AUDIENCIA: REALIZADA - FRUTIFERA", "Frutífera"),
                                            ("Ata recebida.\nAUDIENCIA: INFRUTIFERA\nok", "Infrutífera"),
                                            ("audiência: realizada - infrutífera", "Infrutífera")])
def test_resultado_da_audiencia(texto, esperado):
    av = _avaliar_aud([tram("Secretaria - Envio de Ata", "Concluída", "2026-03-10 10:00:00", texto)],
                      docs_tarefa=[doc("Ata AUD.pdf")])
    assert (av.situacao, av.acao, av.resultado) == (R.PRONTA, R.CONCLUIR_AUDIENCIA, esperado)
    assert R.nome_doc(av.doc) == "Ata AUD.pdf"


def test_trava_resultado_anterior_a_tarefa():
    av = _avaliar_aud([tram("Secretaria - Envio de Ata", "Concluída", "2026-02-01 10:00:00",
                            "AUDIENCIA: INFRUTIFERA")], desde="2026-03-05")
    assert av.situacao == R.AGUARDANDO_RESULTADO


def test_sem_linha_de_resultado_aguarda():
    av = _avaliar_aud([tram("Secretaria - Envio de Ata", "Pendente", texto="aguardando ata; audiência infrutífera?")])
    assert av.situacao == R.AGUARDANDO_RESULTADO
    assert not R.precisa_de_voce(av.situacao)


def test_ata_pelo_nome_padrao_quando_a_tarefa_nao_tem_pdf():
    av = _avaliar_aud([tram("Secretaria - Envio de Ata", "Concluída", "2026-03-10 10:00:00", "AUDIENCIA: FRUTIFERA")],
                      docs_proc=[doc("Ata de audiencia - com acordo - x.pdf"), doc("outra coisa.pdf", id_ged=2)])
    assert R.nome_doc(av.doc) == "Ata de audiencia - com acordo - x.pdf"


def test_audiencia_sem_ata_ainda_conclui():
    av = _avaliar_aud([tram("Secretaria - Envio de Ata", "Concluída", "2026-03-10 10:00:00", "AUDIENCIA: FRUTIFERA")])
    assert av.situacao == R.PRONTA and av.doc is None and "sem ata" in av.detalhe


# ------------------------------------------------------------------ "PRECISA DE VOCÊ"
def test_orfao_vira_instrucao_em_portugues():
    txt = R.o_que_fazer(R.NAO_CONCLUIU, "continuou no form | ANEXO ÓRFÃO no GED: 123", anexo="123")
    assert "anexo 123" in txt and "Exclua" in txt


@pytest.mark.parametrize("situacao,precisa", [(R.PRONTA, False), (R.AGUARDANDO_PECA, False),
                                              (R.CONCLUIDA, False), (R.JA_CONCLUIDA, False),
                                              (R.ERRO, True), (R.NAO_CONCLUIU, True), (R.CPJ_NAO_ACHADO, True),
                                              (R.NAO_EXECUTADA, True), (R.CPJ_SEM_RESPOSTA, False)])
def test_quem_precisa_de_voce(situacao, precisa):
    assert R.precisa_de_voce(situacao) is precisa
