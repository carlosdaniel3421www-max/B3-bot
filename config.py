import os

# ==============================================================================
# CONFIGURAÇÕES DO TELEGRAM
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")

# ==============================================================================
# CONFIGURAÇÕES DA IA (GOOGLE GEMINI)
# ==============================================================================
# A chave deve estar configurada nos Secrets do GitHub (GEMINI_API_KEY)
# ou colada abaixo entre as aspas para testes locais.
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "SUA_CHAVE_GEMINI_AQUI")
GEMINI_MODEL = "gemini-1.5-flash"

# ==============================================================================
# CONFIGURAÇÕES GERAIS E DE ANÁLISE
# ==============================================================================
WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", 
    "WEGE3", "RENT3", "LREN3", "MGLU3", "HAPV3"
]

PERIODO_ANALISE = 60          # Dias históricos
PERIODO_HISTORICO = 60        # Alias para compatibilidade
MEDIA_MOVEL_CURTA = 9
MEDIA_MOVEL_LONGA = 21

# Limites de Score
SCORE_MINIMO_COMPRA = 6.0
SCORE_MINIMO_VENDA = 6.0

# Configurações de Risco e Detalhe (Variáveis que estavam faltando)
RISCO_MAXIMO_ATR_MULT = 2.0   # Multiplicador do ATR para Stop Loss
NIVEL_DETALHE = "COMPLETO"    # Nível de detalhe do relatório (SIMPLES, COMPLETO)

# ==============================================================================
# VALIDAÇÃO
# ==============================================================================
def verificar_configuracoes():
    erros = []
    if not GEMINI_API_KEY or "SUA_CHAVE" in GEMINI_API_KEY:
        # Apenas avisa, não impede a execução se for via ENV
        pass
    
    if not TELEGRAM_BOT_TOKEN or "SEU_TOKEN" in TELEGRAM_BOT_TOKEN:
        erros.append("Token do Telegram não configurado.")
        
    if erros:
        print("⚠️ Avisos de configuração:", erros)
        return False
    return True
