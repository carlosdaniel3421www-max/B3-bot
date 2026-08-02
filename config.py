import os

# ==============================================================================
# CONFIGURAÇÕES DO TELEGRAM E IA
# ==============================================================================

# Leitura das variáveis de ambiente do GitHub Actions
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Modelo da IA (Atualizado para evitar erro 404)
GEMINI_MODEL = "gemini-1.5-flash" 

WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", 
    "WEGE3", "RENT3", "MGLU3", "LREN3"
]

def validar_config():
    print("\n🔍 VERIFICANDO CONFIGURAÇÕES...")
    
    t_len = len(TELEGRAM_TOKEN)
    c_len = len(str(TELEGRAM_CHAT_ID)) if TELEGRAM_CHAT_ID else 0
    g_len = len(GEMINI_API_KEY) if GEMINI_API_KEY else 0
    
    print(f"   • TELEGRAM_TOKEN: {'✅' if t_len > 10 else '❌'} ({t_len} chars)")
    print(f"   • TELEGRAM_CHAT_ID: {'✅' if c_len > 5 else '❌'} ({c_len} chars)")
    print(f"   • GEMINI_API_KEY: {'✅' if g_len > 20 else '❌'} ({g_len} chars)")

    erros = []
    if t_len < 10: erros.append("Token do Telegram inválido.")
    if c_len < 5: erros.append("Chat ID do Telegram inválido.")
    if g_len < 20: erros.append("Chave da API Gemini inválida.")
    
    if erros:
        print("\n❌ ERROS CRÍTICOS:")
        for e in erros: print(f"   - {e}")
        return False
    
    print("\n✅ Configurações OK! Iniciando análise...\n")
    return True
