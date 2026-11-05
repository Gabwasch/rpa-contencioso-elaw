"""Integração sem navegador: tarefas da massa fictícia -> CPJ do mock -> regras -> plano esperado."""
import json
from datetime import timedelta
from pathlib import Path

from elaw import cnj, config, orquestrador as O, regras as R
from elaw.tarefas_xlsx import Tarefa

RAIZ = Path(__file__).resolve().parents[1]

ESPERADO = {
    "contestacao_pronta": (R.PRONTA, R.ANEXAR),
    "contestacao_pronta_prefixo_uf": (R.PRONTA, R.ANEXAR),
    "contestacao_pronta_numerada": (R.PRONTA, R.ANEXAR),
    "contestacao_ja_anexada": (R.PRONTA, R.CONCLUIR_JA_ANEXADA),
    "contestacao_aguardando": (R.AGUARDANDO_PECA, ""),
    "contestacao_pauta_sem_pdf": (R.PAUTA_SEM_PDF, ""),
    "contestacao_pdf_de_outro_processo": (R.PAUTA_SEM_PDF, ""),
    "contestacao_reagendar": (R.PRONTA, R.REAGENDAR),
    "contestacao_reagendar_sem_pdf": (R.PRONTA, R.REAGENDAR),
    "contestacao_dois_clientes": (R.PRONTA, R.ANEXAR),
    "contestacao_nao_achada_cpj": (R.CPJ_NAO_ACHADO, ""),
    "contestacao_anexo_orfao": (R.PRONTA, R.ANEXAR),          # o órfão só aparece na execução (eLaw)
    "contestacao_concluida_por_outra_pessoa": (R.PRONTA, R.ANEXAR),
    "contestacao_falha_no_elaw": (R.PRONTA, R.ANEXAR),
    "audiencia_frutifera": (R.PRONTA, R.CONCLUIR_AUDIENCIA),
    "audiencia_infrutifera": (R.PRONTA, R.CONCLUIR_AUDIENCIA),
    "audiencia_resultado_antigo": (R.AGUARDANDO_RESULTADO, ""),
    "audiencia_sem_resultado": (R.AGUARDANDO_RESULTADO, ""),
    "audiencia_ata_por_nome": (R.PRONTA, R.CONCLUIR_AUDIENCIA),
}


def test_cada_cenario_da_massa_ficticia_leva_ao_desfecho_esperado(app_mock, cliente_cpj, tmp_path):
    cfg = config.carregar(RAIZ / "robo" / "config.toml")
    e = app_mock.state.estado
    tarefas, cenario_por_tarefa = [], {}
    for p in e.processos.values():
        for t in e.tarefas_do_processo(p["id"]):
            # o relatório real só traz tarefas dos últimos 90 dias e dos dois tipos (filtrado no eLaw)
            if t["tipo"] not in ("7101", "7102") or t["registrado"] < e.hoje - timedelta(days=90):
                continue
            tarefas.append(Tarefa(len(tarefas) + 7, p["numero"], e.subtipo(t), "Pendente", str(t["id"]),
                                  t["registrado"].strftime("%d/%m/%Y")))
            cenario_por_tarefa[str(t["id"])] = p["cenario"]
    itens, cont = O.montar_plano(tarefas, cfg)
    O.avaliar_no_cpj(itens, cliente_cpj, cfg, log=lambda *a: None, audit=lambda *a, **k: None, hoje=e.hoje)
    obtido = {cenario_por_tarefa[it.id_tarefa]: (it.situacao, it.acao) for it in itens}
    assert obtido == ESPERADO


def test_seed_e_deterministica_e_todos_os_cnj_sao_validos():
    from mock import seed
    gerado = seed.gerar()
    gravado = json.loads((RAIZ / "mock" / "dados.json").read_text(encoding="utf-8"))
    assert gerado == gravado
    numeros = [p["numero"] for p in gerado["processos"]]
    assert len(set(numeros)) == len(numeros) and all(cnj.validar(n) for n in numeros)
