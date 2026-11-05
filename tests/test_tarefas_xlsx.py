from datetime import datetime

import pytest
from openpyxl import Workbook

from elaw import cnj
from elaw.tarefas_xlsx import ler_tarefas, mapear_colunas

N1 = cnj.gerar(9_200_001, 2026, 8, 26, 11)
N2 = cnj.gerar(9_200_002, 2026, 8, 21, 22)


def _xlsx(tmp_path, linhas, titulo_extra=5, aba="Tarefas"):
    wb = Workbook()
    ws = wb.active
    ws.title = aba
    for i in range(titulo_extra):             # linhas de título antes do cabeçalho
        ws.append([f"Relatório gerado pelo sistema — linha {i + 1}"] if i % 2 == 0 else [])
    for l in linhas:
        ws.append(l)
    arq = tmp_path / "rel.xlsx"
    wb.save(arq)
    return arq


def test_acha_o_cabecalho_fora_da_linha_1(tmp_path):
    arq = _xlsx(tmp_path, [
        ["Processo - ID", "Número do Processo", "Tarefa - ID", "Tarefa - Status", "Sub Tipo", "Data Registrado"],
        [1, N1, 111, "Pendente", "Anexar contestação", "01/03/2026"],
        [],
        [2, N2, 222.0, "Atrasado", "Confirmar realização de audiência", datetime(2026, 3, 2)],
    ])
    tarefas, info = ler_tarefas(arq)
    assert info["linha_cabecalho"] == 6 and info["aba"] == "Tarefas"
    assert set(info["colunas"]) == {"numero", "assunto", "status", "id_tarefa", "data"}
    assert [t.numero for t in tarefas] == [N1, N2]            # linha vazia ignorada
    assert tarefas[1].id_tarefa == "222"                       # 222.0 -> "222"
    assert tarefas[1].data == "02/03/2026"                     # datetime -> dd/mm/aaaa
    assert tarefas[0].assunto == "Anexar contestação"


def test_numero_cai_para_o_padrao_cnj_em_qualquer_celula(tmp_path):
    arq = _xlsx(tmp_path, [["Tarefa - ID", "Sub Tipo", "Observação"],
                           [333, "Anexar contestação", f"ver processo {cnj.so_digitos(N1)} urgente"]], titulo_extra=2)
    tarefas, info = ler_tarefas(arq)
    assert "numero" not in info["colunas"]
    assert tarefas[0].numero == N1


def test_apelidos_igualdade_antes_de_contem():
    mapa = mapear_colunas(["Processo - ID", "Número do Processo", "Status do Processo", "Tarefa - Status"],
                          {"numero": ["numero do processo"], "status": ["tarefa - status", "status"]})
    assert mapa == {"numero": 1, "status": 3}


def test_sem_cabecalho_reconhecivel_avisa(tmp_path):
    arq = _xlsx(tmp_path, [["a", "b"], [1, 2]], titulo_extra=0)
    with pytest.raises(ValueError, match="cabeçalho"):
        ler_tarefas(arq)
