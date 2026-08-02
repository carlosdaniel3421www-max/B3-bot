import os

# ==============================================================================
# CONFIGURAÇÕES DO TELEGRAM
# ==============================================================================
# Obtenha em https://t.me/BotFather
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "SEU_TOKEN_DO_TELEGRAM_AQUI")

# Obtenha em https://t.me/userinfobot (envie /start para ele)
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "SEU_CHAT_ID_AQUI")

# ==============================================================================
# CONFIGURAÇÕES DA IA (GOOGLE GEMINI)
# ==============================================================================
# 1. Crie uma chave gratuita em: https://aistudio.google.com/app/apikey
# 2. No GitHub: Vá em Settings > Secrets and variables > Actions > New repository secret
#    Nome: GEMINI_API_KEY
#    Valor: (cole sua chave aqui)
# 3. Para testes locais, cole a chave abaixo entre as aspas.

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "SUA_CHAVE_GEMINI_AQUI_SEM_ESPACOS")

# Modelo da IA (gemini-1.5-flash é o mais rápido e estável)
GEMINI_MODEL = "gemini-1.5-flash"

# ==============================================================================
# CONFIGURAÇÕES GERAIS DO ROBÔ
# ==============================================================================
# Lista de ativos para monitorar
WATCHLIST = [
    "PETR4",
    "VALE3",
    "ITUB4",
    "BBDC4",
    "BBAS3",
    "WEGE3",
    "RENT3",
    "LREN3",
    "MGLU3",
    "HAPV3"
]

# Configurações de Análise Técnica
PERIODO_ANALISE = 60  # Dias históricos para calcular indicadores
PERIODO_HISTORICO = 60  # Alias necessário para compatibilidade com relatorio_diario.py

MEDIA_MOVEL_CURTA = 9
MEDIA_MOVEL_LONGA = 21

# Limites de Score para disparo de alertas
SCORE_MINIMO_COMPRA = 6.0
SCORE_MINIMO_VENDA = 6.0

# ==============================================================================
# VALIDAÇÃO INICIAL (DEBUG)
# ==============================================================================
def verificar_configuracoes():
    """Verifica se as configurações essenciais estão presentes."""
    erros = []
    
    if TELEGRAM_BOT_TOKEN == "SEU_TOKEN_DO_TELEGRAM_AQUI":
        erros.append("❌ Token do Telegram não configurado.")
        
    if TELEGRAM_CHAT_ID == "SEU_CHAT_ID_AQUI":
        erros.append("❌ Chat ID do Telegram não configurado.")
        
    # Verificação rigorosa da chave da IA
    if not GEMINI_API_KEY or GEMINI_API_KEY == "SUA_CHAVE_GEMINI_AQUI_SEM_ESPACOS":
        erros.append("❌ Chave da API do Gemini (GEMINI_API_KEY) não configurada ou inválida.")
        erros.append("   -> Configure no GitHub Secrets ou edite este arquivo localmente.")
    else:
        print(f"✅ Chave da IA detectada (iniciada com: {GEMINI_API_KEY[:5]}...)")

    if erros:
        print("\n⚠️  ATENÇÃO: Configurações pendentes:")
        for erro in erros:
            print(erro)
        return False
    
    print("\n✅ Todas as configurações validadas com sucesso!")
    return True

# Executa a verificação ao importar o módulo (opcional, remove se causar ruído no log)
if __name__ == "__main__":
    verificar_configuracoes()
