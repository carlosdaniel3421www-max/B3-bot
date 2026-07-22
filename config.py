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
TOP_N_SETUPS = 3          # quantos melhores setups de compra/venda reportar
PERIODO_HISTORICO = "6mo"  # período de dados baixado para os cálculos

# --- Nomes de empresas para busca de notícias (Google News busca melhor por nome) ---
NOME_EMPRESA = {
    "PETR4": "Petrobras", "VALE3": "Vale", "ITUB4": "Itaú Unibanco",
    "BBDC4": "Bradesco", "BBAS3": "Banco do Brasil", "B3SA3": "B3",
    "ABEV3": "Ambev", "WEGE3": "WEG", "RENT3": "Localiza",
    "SUZB3": "Suzano", "PRIO3": "PetroRio", "RADL3": "Raia Drogasil",
    "EQTL3": "Equatorial Energia", "GGBR4": "Gerdau", "LREN3": "Lojas Renner",
    "RAIL3": "Rumo", "HAPV3": "Hapvida", "CSNA3": "CSN", "ELET3": "Eletrobras",
    "ITSA4": "Itaúsa",
}
