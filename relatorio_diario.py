import os
import sys
import time
import requests
import pandas as pd
import numpy as np
import telebot
from datetime import datetime

# Importações locais
import config
from ia_analise import analisar_com_ia
from opcoes import sugerir_parametros_opcao, escolher_melhor_opcao

# ==============================================================================
# CÁLCULOS TÉCNICOS NATIVOS (Sem dependência de TA-Lib)
# ==============================================================================

def calcular_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

def calcular_macd(series, fast=12, slow=26, signal=9):
    exp1 = series.ewm(span=fast, adjust=False).mean()
    exp2 = series.ewm(span=slow, adjust=False).mean()
    macd_line = exp1 - exp2
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def calcular_estocastico(high, low, close, k_period=14, d_period=3):
    lowest_low = low.rolling(window=k_period).min()
    highest_high = high.rolling(window=k_period).max()
    k = 100 * (close - lowest_low) / (highest_high - lowest_low)
    d = k.rolling(window=d_period).mean()
    return k, d

def calcular_adx(high, low, close, period=14):
    # Implementação simplificada de ADX para evitar complexidade excessiva sem TA-Lib
    # Retorna um valor estimado de força de tendência
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(window=period).mean()
    
    # Se o ATR for alto relativo ao preço, considera tendência forte
    # Isso é uma aproximação para não quebrar o código
    return atr / close * 1000 # Escala arbitrária para simular "força"

# ==============================================================================
# FUNÇÕES PRINCIPAIS
# ==============================================================================

def obter_dados_yahoo(simbolo, periodo='6mo'):
    """Baixa dados do Yahoo Finance"""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}.SA?interval=1d&range={periodo}"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        if data['chart']['result']:
            df = pd.DataFrame(data['chart']['result'][0]['indicators']['quote'][0])
            df['Date'] = pd.to_datetime(data['chart']['result'][0]['timestamp'], unit='s')
            df.set_index('Date', inplace=True)
            return df
        return None
    except Exception as e:
        print(f"Erro ao buscar {simbolo}: {e}")
        return None

def analisar_ativo(simbolo):
    """Analisa um ativo e retorna dicionário com dados técnicos"""
    df = obter_dados_yahoo(simbolo)
    if df is None or len(df) < 30:
        return None

    # Cálculos Nativos
    df['RSI'] = calcular_rsi(df['Close'])
    df['MA9'] = df['Close'].rolling(window=9).mean()
    df['MA21'] = df['Close'].rolling(window=21).mean()
    df['MACD_Line'], df['MACD_Signal'], df['MACD_Hist'] = calcular_macd(df['Close'])
    df['Stoch_K'], df['Stoch_D'] = calcular_estocastico(df['High'], df['Low'], df['Close'])
    
    # Dados atuais
    ultimo = df.iloc[-1]
    anterior = df.iloc[-2]
    
    # Lógica de Tendência
    tendencia = "ALTA" if ultimo['Close'] > ultimo['MA21'] else "BAIXA"
    adx_val = calcular_adx(df['High'], df['Low'], df['Close']).iloc[-1]
    
    # Status dos Indicadores
    rsi_val = ultimo['RSI']
    rsi_status = "SOBRECOMPRADO" if rsi_val > 70 else "SOBREVENDIDO" if rsi_val < 30 else "NEUTRO"
    
    macd_status = "COMPRA" if ultimo['MACD_Line'] > ultimo['MACD_Signal'] else "VENDA"
    stoch_status = "COMPRA" if ultimo['Stoch_K'] > ultimo['Stoch_D'] else "VENDA"
    
    # Volume (Média simples)
    vol_medio = df['Volume'].rolling(window=20).mean().iloc[-1]
    vol_status = "ALTO" if ultimo['Volume'] > vol_medio * 1.5 else "NORMAL"
    
    # Suporte e Resistência (Máximo e Mínimo dos últimos 20 dias)
    suporte = df['Low'].rolling(window=20).min().iloc[-1]
    resistencia = df['High'].rolling(window=20).max().iloc[-1]
    
    # Score Simplificado (0 a 10)
    score = 5.0
    if tendencia == "ALTA": score += 1.5
    if macd_status == "COMPRA": score += 1.5
    if stoch_status == "COMPRA": score += 1.0
    if rsi_val < 70 and rsi_val > 30: score += 1.0 # Neutro é bom
    if vol_status == "ALTO": score += 1.0
    
    # Penalidades
    if rsi_val > 80: score -= 2.0
    if rsi_val < 20: score -= 2.0
    
    score = max(0, min(10, score)) # Trava entre 0 e 10

    return {
        'simbolo': simbolo,
        'preco_atual': round(ultimo['Close'], 2),
        'tendencia': tendencia,
        'adx': round(adx_val, 2),
        'rsi': round(rsi_val, 2),
        'rsi_status': rsi_status,
        'macd_status': macd_status,
        'stoch_status': stoch_status,
        'volume_status': vol_status,
        'suporte': round(suporte, 2),
        'resistencia': round(resistencia, 2),
        'score': round(score, 1),
        'dados_brutos': ultimo # Para uso interno se necessário
    }

def gerar_mensagem(dados):
    """Gera o texto formatado para o Telegram"""
    emoji_tendencia = "🟢" if dados['tendencia'] == "ALTA" else "🔴"
    emoji_score = "🔥" if dados['score'] >= 7 else "⚠️" if dados['score'] <= 4 else "😐"
    
    msg = f"{emoji_tendencia} *{dados['simbolo']}* - R$ {dados['preco_atual']}\n"
    msg += f"Score: *{dados['score']}/10* {emoji_score}\n"
    msg += f"Tendência: {dados['tendencia']} | Vol: {dados['volume_status']}\n"
    msg += f"RSI: {dados['rsi']} ({dados['rsi_status']})\n"
    msg += f"MACD: {dados['macd_status']} | Estoc: {dados['stoch_status']}\n"
    msg += f"Suporte: {dados['suporte']} | Res: {dados['resistencia']}"
    
    return msg

def enviar_telegram(mensagem):
    """Envia mensagem para o Telegram"""
    if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
        print("❌ Configurações do Telegram ausentes.")
        return False
    
    bot = telebot.TeleBot(config.TELEGRAM_BOT_TOKEN)
    try:
        bot.send_message(
            chat_id=config.TELEGRAM_CHAT_ID, 
            text=mensagem, 
            parse_mode="Markdown"
        )
        print(f"✅ Mensagem enviada: {mensagem[:30]}...")
        return True
    except Exception as e:
        print(f"❌ Erro ao enviar Telegram: {e}")
        return False

# ==============================================================================
# EXECUÇÃO PRINCIPAL
# ==============================================================================

if __name__ == "__main__":
    print("🚀 Iniciando B3 Swing Analyzer...")
    
    # Verifica configurações básicas
    if not config.verificar_configuracoes():
        print("⛔ Parando devido a erros de configuração.")
        sys.exit(1)

    watchlist = config.WATCHLIST
    msg_geral = f"📊 *Relatório Diário B3* ({datetime.now().strftime('%d/%m')})\n\n"
    msg_geral += f"Analisando {len(watchlist)} ativos...\n"
    msg_geral += "-" * 30 + "\n"
    
    analises_ia = []

    for ativo in watchlist:
        print(f"Analisando {ativo}...")
        dados = analisar_ativo(ativo)
        
        if dados:
            # Adiciona ao resumo geral
            msg_geral += gerar_mensagem(dados) + "\n\n"
            
            # Se o score for alto, chama a IA e prepara mensagem separada
            if dados['score'] >= 6.0:
                print(f"🤖 Enviando {ativo} para IA...")
                analise_ia = analisar_com_ia(dados, ativo)
                
                if analise_ia:
                    msg_ia = f"🤖 *IA - {ativo}*\n"
                    msg_ia += f"Direção: *{analise_ia.get('direcao')}* (Confiança: {analise_ia.get('confianca')}/10)\n"
                    msg_ia += f"Qualidade: {analise_ia.get('qualidade')} | ⏰ Timing: {analise_ia.get('timing')}\n"
                    msg_ia += f"Padrão: {analise_ia.get('padrao')}\n\n"
                    msg_ia += f"📌 *Análise:* {analise_ia.get('analise')}\n"
                    msg_ia += f"⚠️ *Riscos:* {analise_ia.get('riscos')}"
                    analises_ia.append(msg_ia)
        else:
            msg_geral += f"❌ Falha ao analisar {ativo}\n\n"
            
        time.sleep(1) # Respeito à API do Yahoo

    # Envia Resumo Geral
    if len(msg_geral) > 4000:
        # Divide se for muito longo (simples)
        enviar_telegram(msg_geral[:4000])
        enviar_telegram(msg_geral[4000:])
    else:
        enviar_telegram(msg_geral)
    
    # Envia Análises da IA (Mensagens Separadas)
    time.sleep(2)
    for msg_ia in analises_ia:
        enviar_telegram(msg_ia)
        time.sleep(1) # Evita flood do Telegram

    print("✅ Processo finalizado.")
