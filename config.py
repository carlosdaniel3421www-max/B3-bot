import os

# ==============================================================================
# LEITURA DAS VARIÁVEIS DE AMBIENTE (GITHUB SECRETS)
# ==============================================================================
# Usando exatamente os nomes que você criou no GitHub:
# 1. TELEGRAM_TOKEN
# 2. TELEGRAM_CHAT_ID
# 3. GEMINI_API_KEY

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")

# Configurações Padrão
GEMINI_MODEL = "gemini-1.5-flash"

WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", 
    "WEGE3", "RENT3", "MGLU3", "LREN3"
]

def validar_config():
    """
    Verifica se as variáveis foram carregadas corretamente.
    Imprime logs detalhados para debug no GitHub Actions.
    """
    print("\n🔍 VERIFICANDO CONFIGURAÇÕES (GITHUB SECRETS)...")
    
    # Debug: Mostra se as variáveis existem e seu tamanho (não mostra o valor por segurança)
    token_len = len(TELEGRAM_BOT_TOKEN)
    chat_id_val = "Presente" if TELEGRAM_CHAT_ID else "AUSENTE"
    key_len = len(GEMINI_API_KEY)
    
    print(f"   • TELEGRAM_TOKEN: {'✅ Detectado' if token_len > 10 else '❌ FALTANDO'} ({token_len} chars)")
    print(f"   • TELEGRAM_CHAT_ID: {'✅ ' + chat_id_val if TELEGRAM_CHAT_ID else '❌ AUSENTE'}")
    print(f"   • GEMINI_API_KEY: {'✅ Detectado' if key_len > 10 else '❌ FALTANDO'} ({key_len} chars)")

    erros = []
    
    if token_len < 10:
        erros.append("O Secret 'TELEGRAM_TOKEN' não foi encontrado ou é muito curto.")
        
    if not TELEGRAM_CHAT_ID:
        erros.append("O Secret 'TELEGRAM_CHAT_ID' não foi encontrado.")
        
    if key_len < 10:
        erros.append("O Secret 'GEMINI_API_KEY' não foi encontrado ou é inválido.")
    
    if erros:
        print("\n❌ ERROS CRÍTICOS DETECTADOS:")
        for e in erros:
            print(f"   - {e}")
        print("\n💡 DICA: Verifique se os nomes em Settings > Secrets estão EXATAMENTE assim:")
        print("   TELEGRAM_TOKEN")
        print("   TELEGRAM_CHAT_ID")
        print("   GEMINI_API_KEY")
        return False
    
    print("\n✅ TODAS AS CONFIGURAÇÕES VALIDADAS COM SUCESSO!\n")
    return True
