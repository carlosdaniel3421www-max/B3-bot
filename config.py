import os

# Lê as variáveis do GitHub Actions (Secrets)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-1.5-flash"

WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", 
    "WEGE3", "RENT3", "MGLU3", "LREN3"
]

def validar_config():
    """Verifica se os Secrets do GitHub foram carregados."""
    print("🔍 Verificando configurações...")
    
    # Debug para você ver no log do GitHub se está chegando
    token_ok = len(TELEGRAM_BOT_TOKEN) > 10
    chat_ok = len(TELEGRAM_CHAT_ID) > 5
    key_ok = len(GEMINI_API_KEY) > 10
    
    if not token_ok:
        print("❌ ERRO: TELEGRAM_BOT_TOKEN não encontrado ou inválido.")
    if not chat_ok:
        print("❌ ERRO: TELEGRAM_CHAT_ID não encontrado.")
    if not key_ok:
        print("❌ ERRO: GEMINI_API_KEY não encontrada.")
        
    if token_ok and chat_ok and key_ok:
        print("✅ Todas as chaves carregadas com sucesso!")
        return True
    
    print("\n💡 DICA: Vá em Settings > Secrets and variables > Actions")
    print("e crie/edites as secrets com os nomes exatos acima.")
    return False
