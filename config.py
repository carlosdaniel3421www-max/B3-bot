import os

# ==============================================================================
# CONFIGURAÇÕES DO TELEGRAM
# ==============================================================================
# O GitHub Actions usa as Secrets, então o os.environ.get vai pegar o valor de lá.
# Se rodar localmente, use os valores padrão entre aspas para teste.
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", os.environ.get("TELEGRAM_TOKEN", "SEU_TOKEN_AQUI"))
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")

# ==============================================================================
# CONFIGURAÇÕES DA IA (GOOGLE GEMINI)
# ==============================================================================
# A chave deve estar nas Secrets do GitHub com o nome GEMINI_API_KEY
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "SUA_CHAVE_GEMINI_AQUI")
GEMINI_MODEL = "gemini-1.5-flash"

# ==============================================================================
# CONFIGURAÇÕES GERAIS E DE ANÁLISE TÉCNICA
# ==============================================================================
WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", 
    "WEGE3", "RENT3", "LREN3", "MGLU3", "HAPV3"
]

# Períodos para cálculo de indicadores
PERIODO_ANALISE = 60       # Dias históricos para calcular indicadores (alias comum)
PERIODO_HISTORICO = 60     # Variável exigida pelo relatorio_diario.py
NIVEL_DETALHE = "COMPLETO" # Nível de detalhe do relatório (ex: BASICO, COMPLETO)

# Configurações de Médias Móveis
MEDIA_MOVEL_CURTA = 9
MEDIA_MOVEL_LONGA = 21

# Limites de Score para alertas
SCORE_MINIMO_COMPRA = 6.0
SCORE_MINIMO_VENDA = 6.0

# ==============================================================================
# VALIDAÇÃO DE CONFIGURAÇÃO (DEBUG)
# ==============================================================================
def verificar_configuracoes():
    """Imprime o status das configurações para debug."""
    print("--- Verificando Configurações ---")
    
    if "SEU_TOKEN" in str(TELEGRAM_BOT_TOKEN):
        print("⚠️ Aviso: Token do Telegram parece ser o padrão.")
    else:
        print("✅ Token do Telegram configurado.")
        
    if "SUA_CHAVE" in str(GEMINI_API_KEY) or not GEMINI_API_KEY:
        print("⚠️ Aviso: Chave da IA (Gemini) não configurada ou inválida. A análise de IA falhará.")
    else:
        print("✅ Chave da IA configurada.")

    # Verifica variáveis críticas que causaram erro antes
    if 'PERIODO_HISTORICO' not in globals():
        print("❌ Erro Crítico: PERIODO_HISTORICO não definida!")
    else:
        print(f"✅ PERIODO_HISTORICO: {PERIODO_HISTORICO}")
        
    if 'NIVEL_DETALHE' not in globals():
        print("❌ Erro Crítico: NIVEL_DETALHE não definida!")
    else:
        print(f"✅ NIVEL_DETALHE: {NIVEL_DETALHE}")
        
    print("-----------------------------")

# Executa verificação se rodado diretamente
if __name__ == "__main__":
    verificar_configuracoes()
