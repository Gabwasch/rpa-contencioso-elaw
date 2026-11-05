"""
Seletores do eLaw (JSF/PrimeFaces).

Regra de ouro: os ids têm trechos auto-gerados (`j_id_4k7:...`) que MUDAM entre deploys
(no mock, a cada início do servidor). Por isso:
  1. sufixo de id estável           -> [id$=":txtSearch"]
  2. id realmente estável           -> #btnConfirmaSim
  3. texto / papel acessível        -> get_by_role("button", name="Novo Arquivo")
  4. linha de tabela pelo conteúdo  -> índice N da <tr> + sufixo [id$=":N:confirmAgendamentoBtn"]
Nunca: XPath absoluto nem id completo com j_id_*.
"""

# ---- busca de processos (processoList.elaw)
BUSCA_COMBO_TIPO = '[id$=":comboTipoPesquisa_input"]'
BUSCA_TXT = '[id$=":txtSearch"]'
BUSCA_BTN_PESQUISAR = '[id$=":btnPesquisar"]'
BUSCA_DT_BODY = '[id$=":dtProcessoResults_data"]'
BUSCA_BTN_ABRIR_N = '[id$=":dtProcessoResults:{n}:btnProcesso"]'
COL_ID, COL_EMPRESA, COL_PARTE, COL_STATUS, COL_NUMERO = 2, 3, 4, 6, 7
TIPO_PESQUISA_NUMERO = "Número do Processo"
TIPO_PESQUISA_ID = "ID"

# ---- ficha do processo (processoView.elaw) — abas são âncoras sem id: clicar pelo href
ABA_PAUTA = 'a[href="#tabViewProcesso:agendamentosAndamentos"]'
ABA_ANEXOS = 'a[href="#tabViewProcesso:files"]'
DT_TAREFAS_BODY = '[id$=":dtAgendamentoResults_data"]'
TAREFA_BTN_VER_N = '[id$=":dtAgendamentoResults:{n}:verAgendamentoBtn"]'
TAREFA_BTN_CONFIRMAR_N = '[id$=":dtAgendamentoResults:{n}:confirmAgendamentoBtn"]'
VER_IFRAME_HINT = "agendamentoContenciosoView"

# ---- anexos (GED): várias tabelas; a principal tem TODOS os arquivos
GED_TABELAS_BODY = 'tbody[id$="GedEFileViewDt_data"]'
GED_PRINCIPAL_BODY = 'tbody[id$=":gedEFileDataTable:GedEFileViewDt_data"]'
GED_TABELA_PRINCIPAL = "gedEFileDataTable"
GED_BTN_NOVO_TXT = "Novo Arquivo"          # id auto-gerado a cada renderização -> por texto
GED_IFRAME_HINT = "gedEFileUpload"
GED_TIPO_INPUT = '[id$=":eFileTipoCombo_input"]'
GED_FILE_INPUT = '[id$=":uploadGedEFile_input"]'

# ---- form de conclusão (agendamentoContenciosoConfirm.elaw) — abre na MESMA aba
CONFIRM_URL_HINT = "agendamentoContenciosoConfirm"
CONFIRM_BTN_CONFIRMAR = "#btnConfirmaSim"
CONFIRM_BTN_VOLTAR = "#btnVoltar"
CONFIRM_COMBO_PRINCIPAL = '[id$=":CombosCombo_input"]'   # "Anexar defesa?" / "Audiência realizada?"
CONFIRM_RESULTADO_AUDIENCIA = 'select[id$="_input"]:has(option:text-is("Infrutífera"))'
CONFIRM_TIPO_ATA = '[id$=":eFileTipoCombo_input"]'
CONFIRM_FILE_INPUT = 'input[type=file]'
CONFIRM_UPLOAD_LINHAS = 'tbody[id*="gedEFile"][id*="DataTable"] tr[data-ri]'
# selects de Tipo de Documento visíveis no form (topo da área de upload)
CONFIRM_TIPOS_DOC = 'select[id$=":comboEFileTipo_input"]'

# ---- pesquisa de tarefas (agendamentoContenciosoList.elaw)
TAREFAS_BTN_PESQUISAR = '[id$=":btnPesquisar"]'
TAREFAS_BTN_LIMPAR = '[id$=":btnLimparPesquisa"]'
TAREFAS_BTN_EXCEL = '[id$=":btnExcel"]'
TAREFAS_TXT = '[id$=":txtSearch"]'
TAREFAS_COMBO_TIPO_PESQUISA = '[id$=":comboTipoPesquisa_input"]'
TAREFAS_COMBO_TIPO_DATA = '[id$=":comboDataTipo_input"]'
TAREFAS_DATA_INICIO = '[id$=":idDoCalendarStart_input"]'
TAREFAS_DATA_FIM = '[id$=":idDoCalendarEnd_input"]'
TAREFAS_CHK_STATUS = ':status'                         # sufixo do name dos checkboxes
TAREFAS_CHK_TIPO = ':selectManyAgendamentoTipo'
TAREFAS_DT_BODY = '[id$=":dtAgendamentoContenciosoResults_data"]'
GROWL = ".ui-growl-message"
STATUS_PENDENTES, STATUS_ATRASADOS, STATUS_CONCLUIDOS, STATUS_CONFIRMADOS_EM_ATRASO = "1", "4", "2", "6"
TIPO_DATA = {"data": "Agendamento", "dataRegistrado": "Cadastro", "dataConfirmado": "Confirmado"}

# ---- modal "Gerar Relatório" (IFRAME) + "Meus Relatórios"
REL_IFRAME_HINT = "elawReport"
REL_OPCAO_PRECONFIG = "Modelos Pré-Configurado"
REL_BTN_CONTINUAR = '[id$=":continuarBtn"]'
REL_TEMPLATE_INPUT = '[id$=":selectElawReport_input"]'
REL_BTN_GERAR = '[id$=":elawReportGerarBtn"]'
REL_BTN_FECHAR_FINAL = '[id$=":elawReportFecharBtn"]'
MENU_MALETA = 'a:has(.pi-briefcase)'
MEUS_REL_LINK = ".notification-summary"
MEUS_REL_URL_HINT = "userElawReportRequestList"
MEUS_REL_BTN_PESQUISAR = '[id$=":btnPesquisar"]'
MEUS_REL_BTN_LIMPAR = '[id$=":btnLimparPesquisa"]'
MEUS_REL_CLIPE = 'a:has(img[src*="clip.png"])'
