"""
Configurações — preencha com suas chaves antes de rodar o relatório diário.
Por segurança, prefira usar variáveis de ambiente em vez de deixar as
chaves escritas direto aqui (especialmente se for subir isso pro GitHub).
"""

import os

# --- Telegram ---
# Veja instruções em telegram_utils.py (docstring) para gerar o token.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "COLOQUE_SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "COLOQUE_SEU_CHAT_ID_AQUI")

# --- OpLab (opcional, para cadeia de opções real) ---
OPLAB_TOKEN = os.environ.get("OPLAB_TOKEN", "")  # deixe vazio se não tiver

# --- IA visual (Google Gemini) para revisar os sinais olhando o gráfico ---
# Plano GRATUITO (sem prazo de validade): aistudio.google.com -> Get API Key
# Sem chave configurada, o robô usa só o placar técnico (não quebra nada).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
# ==============================
# CONFIGURAÇÃO GEMINI IA
# ==============================

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
)

GEMINI_TIMEOUT_SECONDS = int(
    os.environ.get(
        "GEMINI_TIMEOUT_SECONDS",
        "45"
    )
)

GEMINI_MAX_RETRIES = int(
    os.environ.get(
        "GEMINI_MAX_RETRIES",
        "3"
    )
)
USAR_IA_ANALISE = True

# --- IA híbrida: Gemini descreve o gráfico (grátis) + Nemotron 3 Ultra Free ---
# Chave GRÁTIS do opencode zen (https://opencode.ai/auth -> Keys):
# mesmo modelo que o opencode usa. Sem cartão de crédito.
# Sem chave, volta pro Gemini puro.
CARLOS = os.environ.get("CARLOS", "")
CARLOS_model = os.environ.get("CARLOS_model", "nemotron-3-ultra-free")
CARLOS_base_url = os.environ.get("CARLOS_base_url", "https://opencode.ai/zen/v1")

# --- Screener ---
# Ativos que você opera.
WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBAS3", "WEGE3", "BBDC4", "PRIO3",
    "SUZB3", "B3SA3", "AXIA3", "ABEV3", "RENT3", "EQTL3",
    "JBSS32", "CMIG4", "GGBR4", "USIM5", "RAIL3", "LREN3",
]

NIVEL_DETALHE = 6          # nível mínimo (0-10) para receber plano de entrada completo
PERIODO_HISTORICO = "6mo"  # período de dados baixado para os cálculos

# --- Gestão de risco (calculadora de tamanho de posição) ---
CAPITAL_DISPONIVEL = 10000.0     # capital total que você usa pra operar (ajuste pro seu valor real)
RISCO_POR_OPERACAO_PCT = 1.0     # % do capital que você aceita perder POR operação (1-2% é o padrão de mercado)
RISCO_MAXIMO_ATR_MULT = 3.0      # teto de risco por ação, em múltiplos de ATR (evita stop absurdo em forte tendência)
MARGEM_SAIDA_ESTADO = 2          # zona de amortecimento (em pontos) pra não repetir alerta quando o score oscila perto do gatilho

# --- Calendário de resultados ---
DIAS_MINIMOS_ANTES_RESULTADO = 5  # não sugere entrada se faltar menos que isso pro próximo resultado trimestral

# --- Relatório da tarde (13h, foco em prazo mais curto — até o fim da semana) ---
WATCHLIST_TARDE = ["PETR4", "VALE3", "ITUB4", "WEGE3"]
NIVEL_DETALHE_TARDE = 6       # pode baixar pra 5 se achar que fica sinal demais raro
ATR_MULT_TARDE = 1.0          # stop mais apertado que o padrão (1.5)
RISCO_RETORNO_TARDE = 1.5     # alvo mais próximo (mais fácil de atingir em poucos dias)
MAX_DIAS_HOLDING_TARDE = 5    # referência de prazo (não é usado pro stop/alvo, só informativo no texto)

# --- Nomes de empresas para busca de notícias (Google News busca melhor por nome) ---
NOME_EMPRESA = {
    "PETR4": "Petrobras", "VALE3": "Vale", "ITUB4": "Itaú Unibanco",
    "BBAS3": "Banco do Brasil", "WEGE3": "WEG", "BBDC4": "Bradesco",
    "PRIO3": "PetroRio", "SUZB3": "Suzano", "B3SA3": "B3",
    "AXIA3": "Axia Energia", "ABEV3": "Ambev",
    "RENT3": "Localiza", "EQTL3": "Equatorial Energia", "JBSS32": "JBS",
    "CMIG4": "Cemig", "GGBR4": "Gerdau", "USIM5": "Usiminas",
    "RAIL3": "Rumo", "LREN3": "Lojas Renner",
}
