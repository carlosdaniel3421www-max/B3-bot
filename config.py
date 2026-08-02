import os

# ==============================================================================
# CONFIGURAÇÃO HARDCODED (GARANTIA DE FUNCIONAMENTO)
# ==============================================================================

# 1. Tenta pegar do GitHub (variável de ambiente)
token_env = os.environ.get("TELEGRAM_TOKEN", "")
chat_env = os.environ.get("TELEGRAM_CHAT_ID", "")
gemini_env = os.environ.get("GEMINI_API_KEY", "")

# 2. CONFIGURAÇÃO MANUAL DE EMERGÊNCIA
# Se o GitHub falhar em passar a variável, use estas linhas abaixo:
# Cole seu token EXATO aqui entre as aspas:
TOKEN_MANUAL = "8997172080:AAGkDhNR5KwSS_aYcwtdlZceA3gubaf0YuA" 
CHAT_ID_MANUAL = "" # Deixe vazio se já funcionou acima, ou coloque seu ID aqui também se precisar

# 3. Lógica de Prioridade: Usa o Manual se o Ambiente falhar
TELEGRAM_TOKEN = token_env if len(token_env) > 10 else TOKEN_MANUAL
TELEGRAM_CHAT_ID = chat_env if len(str(chat_env)) > 5 else CHAT_ID_MANUAL
GEMINI_API_KEY = gemini_env if len(gemini_env) > 10 else "" # Gemini geralmente funciona bem via env

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
    if t_len < 10:
        erros.append("Token do Telegram inválido. Verifique se colou no código ou no Secret.")
    if c_len < 5:
        erros.append("Chat ID do Telegram inválido.")
    if g_len < 20:
        erros.append("Chave da API Gemini inválida.")
    
    if erros:
        print("\n❌ ERROS CRÍTICOS:")
        for e in erros: print(f"   - {e}")
        return False
    
    print("\n✅ Configurações OK! Iniciando análise...\n")
    return True
