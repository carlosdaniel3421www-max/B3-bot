"""
Configurações — preencha com suas chaves antes de rodar o relatório diário.
Por segurança, prefira usar variáveis de ambiente em vez de deixar as
chaves escritas direto aqui (especialmente se for subir isso pro GitHub).
"""

import os
import logging


def _inteiro_positivo_ambiente(nome, padrao):
    try:
        valor = int(os.environ.get(nome, str(padrao)))
        if valor > 0:
            return valor
    except ValueError:
        pass
    logging.getLogger(__name__).warning("%s inválido; usando padrão %s", nome, padrao)
    return padrao

# --- Telegram ---
# Veja instruções em telegram_utils.py (docstring) para gerar o token.
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "COLOQUE_SEU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "COLOQUE_SEU_CHAT_ID_AQUI")

# --- OpLab (opcional, para cadeia de opções real) ---
OPLAB_TOKEN = os.environ.get("OPLAB_TOKEN", "")  # deixe vazio se não tiver

# Novas entradas; nao filtra a cadeia bruta usada na gestao de posicoes.
OPCOES_MIN_DIAS_CORRIDOS = 14
OPCOES_MAX_DIAS_CORRIDOS = 30

# --- GitHub (para acionar o relatório via /relatorio no Telegram) ---
# Crie em: Settings -> Developer settings -> Personal access tokens -> Fine-grained tokens
# Permissão necessária: Actions: Write (no repositório B3-bot)
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# --- IA visual (Google Gemini) para revisar os sinais olhando o gráfico ---
# Chave: aistudio.google.com -> Get API Key. Cotas e acesso dependem da conta.
# Sem chave configurada, o robô usa só o placar técnico (não quebra nada).
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
# ==============================
# CONFIGURAÇÃO GEMINI IA
# ==============================

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.5-flash-lite"
).strip() or "gemini-3.5-flash-lite"

GEMINI_TIMEOUT_SECONDS = _inteiro_positivo_ambiente("GEMINI_TIMEOUT_SECONDS", 45)

GEMINI_MAX_RETRIES = _inteiro_positivo_ambiente("GEMINI_MAX_RETRIES", 3)
USAR_IA_ANALISE = True

# --- IA híbrida: Gemini descreve o gráfico + Nemotron ---
# Chave do opencode zen (https://opencode.ai/auth -> Keys).
# Nomes configurados não garantem disponibilidade nem gratuidade do provedor.
# Sem chave, volta pro Gemini puro.
CARLOS = os.environ.get("CARLOS", "").strip()
CARLOS_model = os.environ.get("CARLOS_model", "nemotron-3-ultra-free").strip() or "nemotron-3-ultra-free"
CARLOS_base_url = os.environ.get("CARLOS_base_url", "https://opencode.ai/zen/v1").strip() or "https://opencode.ai/zen/v1"

# --- Screener ---
# Ativos que você opera.
WATCHLIST = [
    "PETR4", "VALE3", "ITUB4", "BBAS3", "WEGE3", "BBDC4", "PRIO3",
    "SUZB3", "B3SA3", "AXIA3", "ABEV3", "RENT3", "EQTL3",
    "JBSS32", "CMIG4", "GGBR4", "USIM5", "RAIL3", "LREN3",
]

NIVEL_DETALHE = 6          # nível mínimo (0-10) para receber plano de entrada completo
PERIODO_HISTORICO = "2y"   # período de dados baixado para os cálculos (2 anos p/ SMA200 e contexto histórico)

# --- Gestão de risco (calculadora de tamanho de posição) ---
CAPITAL_DISPONIVEL = 10000.0     # capital total que você usa pra operar (ajuste pro seu valor real)
RISCO_POR_OPERACAO_PCT = 1.0     # % do capital que você aceita perder POR operação (1-2% é o padrão de mercado)
RISCO_MAXIMO_ATR_MULT = 3.0      # teto de risco por ação, em múltiplos de ATR (evita stop absurdo em forte tendência)
MARGEM_SAIDA_ESTADO = 2          # zona de amortecimento (em pontos) pra não repetir alerta quando o score oscila perto do gatilho

# --- Politica de candidatos e carteira (hipoteses a validar em simulacao) ---
EXIGIR_SETUP = True  # Candidato exige gatilho posterior; nao e ordem executada.
RISCO_MAX_CARTEIRA_PCT = 3.0
EXPOSICAO_MAX_SETOR_PCT = 40.0
SETORES = {
    "PETR4": "petroleo", "PRIO3": "petroleo", "VALE3": "mineracao",
    "ITUB4": "bancos", "BBAS3": "bancos", "BBDC4": "bancos",
    "CMIG4": "energia", "AXIA3": "energia", "EQTL3": "energia",
    "WEGE3": "industria", "SUZB3": "celulose", "B3SA3": "bolsa",
    "ABEV3": "bebidas", "RENT3": "locacao", "JBSS32": "alimentos",
    "GGBR4": "siderurgia", "USIM5": "siderurgia", "RAIL3": "logistica",
    "LREN3": "varejo",
}

# --- Calendário de resultados ---
DIAS_MINIMOS_ANTES_RESULTADO = 5  # não sugere entrada se faltar menos que isso pro próximo resultado trimestral

# --- Nomes de empresas para busca de notícias (Google News busca melhor por nome) ---
NOME_EMPRESA = {
    "PETR4": "Petrobras", "VALE3": "Vale", "ITUB4": "Itaú Unibanco",
    "BBAS3": "Banco do Brasil", "WEGE3": "WEG", "BBDC4": "Bradesco",
    "PRIO3": "PetroRio", "SUZB3": "Suzano", "B3SA3": "B3",
    "AXIA3": "Axia Energia", "ABEV3": "Ambev",
    "RENT3": "Localiza", "EQTL3": "Equatorial Energia", "JBSS32": "JBS",
    "CMIG4": "Cemig", "GGBR4": "Gerdau", "USIM5": "Usiminas",
    "RAIL3": "Rumo", "LREN3": "Lojas Renner",
}
