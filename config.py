import os

# --- TELEGRAM ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

# --- IA (GEMINI) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-1.5-flash"

# --- CONFIGURAÇÕES DO ROBÔ ---
WATCHLIST = ["PETR4", "VALE3", "ITUB4", "BBDC4", "WEGE3", "RENT3", "MGLU3"]
PERIODO_HISTORICO = 60
NIVEL_DETALHE = "resumo" # ou "completo"
RISCO_MAXIMO_ATR_MULT = 2.0
MARGEM_SAIDA_ESTADO = 0.02

def validar_config():
    erros = []
    if not TELEGRAM_BOT_TOKEN: erros.append("Token Telegram faltando")
    if not TELEGRAM_CHAT_ID: erros.append("Chat ID Telegram faltando")
    if not GEMINI_API_KEY: erros.append("Chave Gemini faltando")
    
    if erros:
        print("❌ ERROS DE CONFIGURAÇÃO:")
        for e in erros: print(f"- {e}")
        return False
    print("✅ Configurações validadas.")
    return True
