cat > config.py << 'EOF'
import os

# ==============================================================================
# CONFIGURAÇÕES DO TELEGRAM
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "SEU_TOKEN_DO_TELEGRAM_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")

# ==============================================================================
# CONFIGURAÇÕES DA IA (GOOGLE GEMINI)
# ==============================================================================
# IMPORTANTE: Configure esta chave nos Secrets do GitHub (Settings > Secrets > Actions)
# Nome: GEMINI_API_KEY
# Valor: (sua chave do Google AI Studio)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "SUA_CHAVE_GEMINI_AQUI_SEM_ESPACOS")
GEMINI_MODEL = "gemini-1.5-flash"

# ==============================================================================
# CONFIGURAÇÕES GERAIS DO ROBÔ
# ==============================================================================
WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3",
    "WEGE3", "RENT3", "LREN3", "MGLU3", "HAPV3"
]

# Período de dias históricos para análise (Variável que estava faltando)
PERIODO_HISTORICO = 60 
PERIODO_ANALISE = 60   # Alias para compatibilidade

# Médias Móveis
MEDIA_MOVEL_CURTA = 9
MEDIA_MOVEL_LONGA = 21

# Limites de Score
SCORE_MINIMO_COMPRA = 6.0
SCORE_MINIMO_VENDA = 6.0

# ==============================================================================
# VALIDAÇÃO
# ==============================================================================
def verificar_configuracoes():
    erros = []
    if TELEGRAM_BOT_TOKEN == "SEU_TOKEN_DO_TELEGRAM_AQUI":
        erros.append("❌ Token do Telegram não configurado.")
    if TELEGRAM_CHAT_ID == "SEU_CHAT_ID_AQUI":
        erros.append("❌ Chat ID do Telegram não configurado.")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "SUA_CHAVE_GEMINI_AQUI_SEM_ESPACOS":
        erros.append("⚠️ Chave da API do Gemini não configurada (IA não funcionará).")
    
    if erros:
        print("\n⚠️  ATENÇÃO - Configurações pendentes:")
        for e in erros:
            print(e)
        return False
    
    print("\n✅ Configurações validadas!")
    return True

if __name__ == "__main__":
    verificar_configuracoes()
EOF
