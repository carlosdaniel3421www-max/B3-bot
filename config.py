import os

# ==============================================================================
# CONFIGURAÇÕES DO TELEGRAM
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "SEU_TOKEN_DO_TELEGRAM_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")

# ==============================================================================
# CONFIGURAÇÕES DA IA (GOOGLE GEMINI)
# ==============================================================================
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "SUA_CHAVE_GEMINI_AQUI")
GEMINI_MODEL = "gemini-1.5-flash"

# ==============================================================================
# CONFIGURAÇÕES GERAIS E DE ANÁLISE TÉCNICA
# ==============================================================================
WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", 
    "WEGE3", "RENT3", "LREN3", "MGLU3", "HAPV3"
]

PERIODO_ANALISE = 60
MEDIA_MOVEL_CURTA = 9
MEDIA_MOVEL_LONGA = 21

# Variáveis solicitadas pelo relatorio_diario.py (Correção de Erros)
PERIODO_HISTORICO = 60
NIVEL_DETALHE = "COMPLETO"
RISCO_MAXIMO_ATR_MULT = 2.0
MARGEM_SAIDA_ESTADO = 0.05

SCORE_MINIMO_COMPRA = 6.0
SCORE_MINIMO_VENDA = 6.0

# ==============================================================================
# VALIDAÇÃO INICIAL
# ==============================================================================
def verificar_configuracoes():
    erros = []
    
    if TELEGRAM_BOT_TOKEN == "SEU_TOKEN_DO_TELEGRAM_AQUI":
        erros.append("❌ Token do Telegram não configurado.")
        
    if TELEGRAM_CHAT_ID == "SEU_CHAT_ID_AQUI":
        erros.append("❌ Chat ID do Telegram não configurado.")
        
    if not GEMINI_API_KEY or GEMINI_API_KEY == "SUA_CHAVE_GEMINI_AQUI":
        erros.append("❌ Chave da API do Gemini não configurada.")
    else:
        print(f"✅ Chave da IA detectada (iniciada com: {GEMINI_API_KEY[:5]}...)")

    if erros:
        print("\n⚠️ ATENÇÃO: Configurações pendentes:")
        for erro in erros:
            print(erro)
        return False
    
    print("\n✅ Todas as configurações validadas com sucesso!")
    return True

if __name__ == "__main__":
    verificar_configuracoes()
