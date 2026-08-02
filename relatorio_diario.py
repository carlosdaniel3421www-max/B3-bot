import pandas as pd
import numpy as np
import config
import yfinance as yf
from datetime import datetime
import telebot
from opcoes import analisar_gregas_portifolio, escolher_melhor_opcao
from ia_analise import analisar_com_ia

# Inicialização do Bot
bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)

def obter_dados(ativo, periodo):
    try:
        ticker = yf.Ticker(f"{ativo}.SA")
        df = ticker.history(period=f"{periodo}d")
        if df.empty:
            return None
        return df
    except Exception as e:
        print(f"Erro ao obter dados de {ativo}: {e}")
        return None

def calcular_indicadores(df):
    df['MM9'] = df['Close'].rolling(window=9).mean()
    df['MM21'] = df['Close'].rolling(window=21).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_MACD'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # Estocástico
    low_14 = df['Low'].rolling(window=14).min()
    high_14 = df['High'].rolling(window=14).max()
    df['K'] = 100 * ((df['Close'] - low_14) / (high_14 - low_14))
    df['D'] = df['K'].rolling(window=3).mean()
    
    # ATR (Volatilidade)
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['ATR'] = true_range.rolling(14).mean()
    
    return df

def avaliar_ativo(df, ativo):
    ultimo = df.iloc[-1]
    anterior = df.iloc[-2]
    
    score = 0
    detalhes = []
    
    # Tendência
    tendencia = "NEUTRA"
    if ultimo['MM9'] > ultimo['MM21']:
        tendencia = "ALTA"
        score += 3
        detalhes.append("🟢 Tendência de Alta (MM9 > MM21)")
    elif ultimo['MM9'] < ultimo['MM21']:
        tendencia = "BAIXA"
        detalhes.append("🔴 Tendência de Baixa (MM9 < MM21)")
    
    # RSI
    rsi_status = "NEUTRO"
    if ultimo['RSI'] > 70:
        rsi_status = "SOBRECOMPRA"
        score -= 1
        detalhes.append(f"⚠️ RSI Sobrecompra ({ultimo['RSI']:.1f})")
    elif ultimo['RSI'] < 30:
        rsi_status = "SOBREVENDA"
        score += 2
        detalhes.append(f"💰 RSI Sobrevenda ({ultimo['RSI']:.1f})")
    else:
        detalhes.append(f"➖ RSI Neutro ({ultimo['RSI']:.1f})")
        
    # MACD
    macd_status = "NEUTRO"
    if ultimo['MACD'] > ultimo['Signal_MACD'] and anterior['MACD'] <= anterior['Signal_MACD']:
        macd_status = "CRUZOU_PARA_CIMA"
        score += 2
        detalhes.append("🚀 MACD Cruzou para Cima")
    elif ultimo['MACD'] < ultimo['Signal_MACD'] and anterior['MACD'] >= anterior['Signal_MACD']:
        macd_status = "CRUZOU_PARA_BAIXO"
        score -= 2
        detalhes.append("📉 MACD Cruzou para Baixo")
        
    # Volume
    vol_medio = df['Volume'].rolling(window=20).mean().iloc[-1]
    volume_status = "NORMAL"
    if ultimo['Volume'] > vol_medio * 1.5:
        volume_status = "ALTO"
        score += 1
        detalhes.append("🔥 Volume Acima da Média")
    
    # Cálculo final do score (0 a 10)
    score_final = min(10, max(0, score + 5)) # Base 5 + ajustes
    
    return {
        "ativo": ativo,
        "preco_atual": ultimo['Close'],
        "tendencia": tendencia,
        "rsi": ultimo['RSI'],
        "macd_status": macd_status,
        "score": score_final,
        "detalhes": detalhes,
        "atr": ultimo['ATR'],
        "suporte": df['Low'].rolling(window=20).min().iloc[-1],
        "resistencia": df['High'].rolling(window=20).max().iloc[-1]
    }

def gerar_e_enviar_relatorio():
    print("🤖 Iniciando geração do relatório diário...")
    
    # Verificação de segurança das configs (Valores Default se falhar)
    risco_mult = getattr(config, 'RISCO_MAXIMO_ATR_MULT', 2.0)
    margem_saida = getattr(config, 'MARGEM_SAIDA_ESTADO', 0.02)
    nivel_detalhe = getattr(config, 'NIVEL_DETALHE', "COMPLETO")
    periodo_hist = getattr(config, 'PERIODO_HISTORICO', 60)
    
    mensagem_resumo = "📊 *RELATÓRIO DIÁRIO B3 - OPÇÕES*\n\n"
    mensagem_ia = ""
    
    ativos_analisados = []
    
    for ativo in config.WATCHLIST:
        print(f"Analisando {ativo}...")
        df = obter_dados(ativo, periodo_hist)
        
        if df is None or len(df) < 20:
            continue
            
        df = calcular_indicadores(df)
        analise = avaliar_ativo(df, ativo)
        ativos_analisados.append(analise)
        
        # Monta mensagem técnica
        emoji = "🟢" if analise['score'] >= 7 else "🔴" if analise['score'] <= 4 else "🟡"
        mensagem_resumo += f"{emoji} *{ativo}* - Score: *{analise['score']}/10*\n"
        mensagem_resumo += f"   Preço: R$ {analise['preco_atual']:.2f} | Tendência: {analise['tendencia']}\n"
        mensagem_resumo += f"   RSI: {analise['rsi']:.1f} | ATR: {analise['atr']:.2f}\n"
        
        # --- CHAMADA DA IA ---
        # Prepara dados para a IA
        dados_ia = {
            "preco_atual": analise['preco_atual'],
            "tendencia": analise['tendencia'],
            "rsi": analise['rsi'],
            "macd_status": analise['macd_status'],
            "score": analise['score'],
            "atr": analise['atr'],
            "suporte": analise['suporte'],
            "resistencia": analise['resistencia']
        }
        
        resultado_ia = analisar_com_ia(dados_ia, ativo)
        
        if resultado_ia:
            mensagem_ia += f"\n🤖 *IA: {ativo}*\n"
            mensagem_ia += f"   Direção: *{resultado_ia.get('direcao', 'NEUTRO')}* (Confiança: {resultado_ia.get('confianca', 0)}/10)\n"
            mensagem_ia += f"   Padrão: {resultado_ia.get('padrao', 'N/A')}\n"
            mensagem_ia += f"   📌 Análise: {resultado_ia.get('analise', 'Sem detalhes')}\n"
            if resultado_ia.get('riscos'):
                mensagem_ia += f"   ⚠️ Riscos: {resultado_ia.get('riscos')}\n"
            mensagem_ia += "------------------------\n"
        else:
            # Se a IA falhar, não quebra o robô, apenas segue sem a mensagem dela
            print(f"⚠️ IA não retornou análise para {ativo}.")

    # Envia Resumo Técnico
    if mensagem_resumo:
        try:
            bot.send_message(config.TELEGRAM_CHAT_ID, mensagem_resumo, parse_mode="Markdown")
            print("✅ Relatório técnico enviado.")
        except Exception as e:
            print(f"Erro ao enviar resumo: {e}")
    
    # Envia Análise da IA (Separada)
    if mensagem_ia:
        try:
            # Pequeno delay para não estourar limite de rate do Telegram
            import time
            time.sleep(1)
            bot.send_message(config.TELEGRAM_CHAT_ID, mensagem_ia, parse_mode="Markdown")
            print("✅ Análise da IA enviada.")
        except Exception as e:
            print(f"Erro ao enviar análise IA: {e}")
    else:
        print("ℹ️ Nenhuma análise de IA gerada (verifique a chave da API ou logs).")

if __name__ == "__main__":
    # Valida configs antes de rodar
    if config.verificar_configuracoes():
        gerar_e_enviar_relatorio()
    else:
        print("❌ Erro crítico de configuração. Robô abortado.")
