import os

# ==============================================================================
# CONFIGURAÇÕES DO TELEGRAM
# ==============================================================================
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "SEU_TOKEN_DO_TELEGRAM_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")

# ==============================================================================
# CONFIGURAÇÕES DA IA (GOOGLE GEMINI)
# ==============================================================================
# Certifique-se de configurar esta variável no GitHub Secrets (Settings > Secrets > Actions)
# Nome da variável: GEMINI_API_KEY
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "SUA_CHAVE_GEMINI_AQUI")
GEMINI_MODEL = "gemini-1.5-flash"

# ==============================================================================
# CONFIGURAÇÕES GERAIS E DE ANÁLISE TÉCNICA
# ==============================================================================
WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", 
    "WEGE3", "RENT3", "LREN3", "MGLU3", "HAPV3"
]

PERIODO_ANALISE = 60          # Dias históricos para indicadores
PERIODO_HISTORICO = 60        # Alias necessário para o relatorio_diario.py
MEDIA_MOVEL_CURTA = 9
MEDIA_MOVEL_LONGA = 21

# Limites de Score
SCORE_MINIMO_COMPRA = 6.0
SCORE_MINIMO_VENDA = 6.0

# ==============================================================================
# CONFIGURAÇÕES DE RISCO E OPERACIONAL (Novas variáveis exigidas)
# ==============================================================================
RISCO_MAXIMO_ATR_MULT = 2.0       # Multiplicador do ATR para Stop Loss
MARGEM_SAIDA_ESTADO = 0.02        # Margem de segurança para saída (2%)
NIVEL_DETALHE = "COMPLETO"        # Nível de detalhe do relatório: "SIMPLES" ou "COMPLETO"

# Configurações de Opções (Caso use o módulo de opções)
DELTA_ALVO = 0.40
VENCIMENTO_MINIMO_DIAS = 7

# ==============================================================================
# FUNÇÃO DE VALIDAÇÃO
# ==============================================================================
def verificar_configuracoes():
    """Verifica se as configurações essenciais estão presentes."""
    erros = []
    
    if TELEGRAM_BOT_TOKEN == "SEU_TOKEN_DO_TELEGRAM_AQUI":
        erros.append("❌ Token do Telegram não configurado.")
    if TELEGRAM_CHAT_ID == "SEU_CHAT_ID_AQUI":
        erros.append("❌ Chat ID do Telegram não configurado.")
    if not GEMINI_API_KEY or GEMINI_API_KEY == "SUA_CHAVE_GEMINI_AQUI":
        # Apenas avisa, não impede a execução se for teste sem IA
        print("⚠️ Aviso: Chave da API do Gemini não configurada. A análise por IA será ignorada.")
    else:
        print(f"✅ Chave da IA detectada (iniciada com: {GEMINI_API_KEY[:5]}...)")

    if erros:
        print("\n⚠️ ERROS CRÍTICOS DE CONFIGURAÇÃO:")
        for erro in erros:
            print(erro)
        return False
    
    print("✅ Configurações carregadas com sucesso.")
    return True

if __name__ == "__main__":
    verificar_configuracoes()
