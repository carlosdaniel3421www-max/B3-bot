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

# --- Screener ---
# Ativos que você opera.
WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBAS3", "WEGE3", "BBDC4", "PRIO3",
    "SUZB3", "B3SA3", "ELET3", "ELET6", "ABEV3", "RENT3", "EQTL3",
    "JBSS3", "CMIG4", "GGBR4", "USIM5", "RAIL3", "LREN3",
]

NIVEL_DETALHE = 6          # nível mínimo (0-10) para receber plano de entrada completo
PERIODO_HISTORICO = "6mo"  # período de dados baixado para os cálculos

# --- Gestão de risco (calculadora de tamanho de posição) ---
CAPITAL_DISPONIVEL = 10000.0     # capital total que você usa pra operar (ajuste pro seu valor real)
RISCO_POR_OPERACAO_PCT = 1.0     # % do capital que você aceita perder POR operação (1-2% é o padrão de mercado)

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
    "ELET3": "Eletrobras", "ELET6": "Eletrobras", "ABEV3": "Ambev",
    "RENT3": "Localiza", "EQTL3": "Equatorial Energia", "JBSS3": "JBS",
    "CMIG4": "Cemig", "GGBR4": "Gerdau", "USIM5": "Usiminas",
    "RAIL3": "Rumo", "LREN3": "Lojas Renner",
}
