"""Modo guiado (perguntas S/N separadas, confirmação parcial) e a planilha da rodada (duas abas).
Tudo com itens fictícios, sem navegador."""
import os
import time
from datetime import datetime

from openpyxl import load_workbook

from elaw import guiado as G, regras as R, saida
from elaw.orquestrador import FILA_AUDIENCIA, FILA_CONTESTACAO, Item


def _item(id_tarefa, situacao, acao="", fila=FILA_CONTESTACAO, antes="", **kw):
    return Item(fila, 7, f"0000{id_tarefa}-00.2026.8.00.0001", str(id_tarefa), "", "Pendente", "01/01/2026",
                situacao=situacao, acao=acao, antes=antes, **kw)


def _respostas(*sim_nao):
    """perguntar() falso: devolve as respostas em ordem e guarda as perguntas feitas."""
    fila, feitas = list(sim_nao), []

    def perguntar(texto):
        feitas.append(texto)
        return fila.pop(0)
    perguntar.feitas = feitas
    return perguntar


def _plano():
    anexar = _item(1, R.PRONTA, R.ANEXAR)
    reag = _item(2, R.PRONTA, R.REAGENDAR, antes=R.AGUARDANDO_PECA)
    ja = _item(3, R.PRONTA, R.CONCLUIR_JA_ANEXADA)
    aguardando = _item(4, R.AGUARDANDO_PECA)
    itens = [anexar, reag, ja, aguardando]
    return itens, [anexar, reag, ja]


# ------------------------------------------------------------------ duas perguntas S/N
def test_sim_nas_duas_perguntas_devolve_todas_na_ordem_do_plano():
    itens, prontas = _plano()
    perguntar = _respostas(True, True)
    assert G.confirmar_rodada(itens, prontas, perguntar) == prontas
    assert len(perguntar.feitas) == 2
    assert "as 2 prontas" in perguntar.feitas[0] and "Reagendar a tarefa" in perguntar.feitas[1]


def test_so_as_prontas_sem_os_reagendamentos_e_o_recusado_volta_a_aguardando():
    itens, prontas = _plano()
    escolhidas = G.confirmar_rodada(itens, prontas, _respostas(True, False))
    assert [it.id_tarefa for it in escolhidas] == ["1", "3"]
    reag = itens[1]
    assert (reag.situacao, reag.acao, reag.antes) == (R.AGUARDANDO_PECA, "", "")
    assert not R.precisa_de_voce(reag.situacao, reag.acao, reag.antes)


def test_reagendamento_recusado_de_pauta_sem_pdf_continua_na_lista_do_operador():
    reag = _item(5, R.PRONTA, R.REAGENDAR, antes=R.PAUTA_SEM_PDF)
    assert G.confirmar_rodada([reag], [reag], _respostas(False)) == []
    assert reag.situacao == R.PAUTA_SEM_PDF and R.precisa_de_voce(reag.situacao, reag.acao, reag.antes)


def test_so_os_reagendamentos():
    itens, prontas = _plano()
    escolhidas = G.confirmar_rodada(itens, prontas, _respostas(False, True))
    assert [it.id_tarefa for it in escolhidas] == ["2"]
    assert itens[0].situacao == R.PRONTA      # a pronta recusada continua pronta (fica para outra rodada)


def test_sem_reagendamento_faz_uma_pergunta_so_no_singular():
    pronta = _item(1, R.PRONTA, R.ANEXAR)
    perguntar = _respostas(True)
    assert G.confirmar_rodada([pronta], [pronta], perguntar) == [pronta]
    assert perguntar.feitas == ["  Concluir a tarefa pronta agora? [S/N]: "]


def test_consulta_so_com_reagendamento_pergunta_reagendar():
    reag = _item(2, R.PRONTA, R.REAGENDAR, antes=R.AGUARDANDO_PECA)
    perguntar = _respostas(True)
    assert G.confirmar_consulta([reag], [reag], perguntar) is True
    assert perguntar.feitas[0].startswith("  Reagendar a tarefa pronta")


def test_resumo_da_rodada_conta_prontas_que_ficaram_para_depois():
    itens = [_item(1, R.CONCLUIDA), _item(2, R.REAGENDADA, antes=R.AGUARDANDO_PECA), _item(3, R.PRONTA, R.ANEXAR),
             _item(4, R.AGUARDANDO_PECA), _item(5, R.ERRO), _item(6, R.JA_CONCLUIDA)]
    assert G.resumo_da_rodada(itens) == ("1 concluídas pelo robô · 1 reagendadas · 1 já estavam concluídas · "
                                         "1 prontas ficaram para outra rodada · 1 aguardando · 1 precisam de você")


# ------------------------------------------------------------------ planilha da rodada
def _rodada_executada():
    return [
        _item(1, R.CONCLUIDA, R.ANEXAR, pdf="/tmp/pdfs/Contestação - processo 1.pdf", anexo="9001"),
        _item(2, R.CONCLUIDA_JA_ANEXADA, R.CONCLUIR_JA_ANEXADA, anexo="9002"),
        _item(3, R.REAGENDADA, R.REAGENDAR, antes=R.AGUARDANDO_PECA),
        _item(4, R.CONCLUIDA, R.CONCLUIR_AUDIENCIA, fila=FILA_AUDIENCIA, resultado="Frutífera", anexo="9004"),
        _item(5, R.JA_CONCLUIDA, R.ANEXAR),                  # foi outra pessoa: não entra em "Feito pelo robô"
        _item(6, R.AGUARDANDO_PECA),
    ]


def test_planilha_tem_as_duas_abas_e_ja_concluida_nao_conta_como_feita(tmp_path):
    itens = _rodada_executada() + [_item(7, R.ERRO, R.ANEXAR, detalhe="TimeoutError: botão não apareceu")]
    arq = tmp_path / saida.ARQUIVO_RODADA
    assert saida.gravar_planilha_da_rodada(itens, arq, quando=datetime(2026, 1, 20, 9, 30)) == (1, 4)
    wb = load_workbook(arq)
    assert wb.sheetnames == ["Precisa de você", "Feito pelo robô"]
    assert wb.active.title == "Precisa de você"             # há o que fazer: abre na lista do operador
    voce = list(wb["Precisa de você"].iter_rows(min_row=2, values_only=True))
    assert [ln[1] for ln in voce] == ["7"]
    feito = list(wb["Feito pelo robô"].iter_rows(min_row=2, values_only=True))
    assert [ln[2] for ln in feito] == ["1", "2", "3", "4"]
    assert feito[0][0] == "20/01/2026 09:30"
    assert feito[0][3:] == ("Anexar contestação", "Contestação anexada e tarefa concluída",
                            "Contestação - processo 1.pdf", "9001")
    assert "Prazo de contestação em curso" in feito[2][4]
    assert feito[3][3:5] == ("Confirmar audiência", "Audiência confirmada como Frutífera e ata anexada")


def test_sem_nada_para_a_equipe_abre_direto_no_que_foi_feito(tmp_path):
    arq = tmp_path / saida.ARQUIVO_RODADA
    assert saida.gravar_planilha_da_rodada(_rodada_executada(), arq) == (0, 4)
    wb = load_workbook(arq)
    assert wb.active.title == "Feito pelo robô"
    assert list(wb["Precisa de você"].iter_rows(min_row=2, values_only=True))[0][0].startswith("Nada precisa")


def test_dry_run_deixa_a_aba_do_robo_com_o_aviso(tmp_path):
    arq = tmp_path / saida.ARQUIVO_RODADA
    plano = [_item(1, R.PRONTA, R.ANEXAR), _item(2, R.CPJ_NAO_ACHADO)]
    assert saida.gravar_planilha_da_rodada(plano, arq) == (1, 0)
    wb = load_workbook(arq)
    assert wb.active.title == "Precisa de você"
    assert list(wb["Feito pelo robô"].iter_rows(min_row=2, values_only=True))[0][0].startswith("O robô não gravou")


def test_audiencia_sem_ata():
    it = _item(1, R.CONCLUIDA, R.CONCLUIR_AUDIENCIA, fila=FILA_AUDIENCIA, resultado="Infrutífera")
    assert saida.o_que_o_robo_fez(it) == "Audiência confirmada como Infrutífera (sem ata)"


def test_ultima_planilha_pega_a_rodada_mais_recente(tmp_path):
    assert G.ultima_planilha(tmp_path) is None
    for n, nome in enumerate(("2026-01-19_090000", "2026-01-20_090000")):
        (tmp_path / nome).mkdir()
        arq = tmp_path / nome / saida.ARQUIVO_RODADA
        arq.write_bytes(b"")
        os.utime(arq, (time.time() - 100 + n * 50,) * 2)
    assert G.ultima_planilha(tmp_path).parent.name == "2026-01-20_090000"
