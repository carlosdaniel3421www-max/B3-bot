import pandas as pd
import numpy as np
import requests

def buscar_dados_yahoo(simbolo, periodo=60):
    """Busca dados históricos no Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}.SA"
    params = {"range": f"{periodo}d", "interval": "1d"}
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=10)
        data = resp.json()
        if 'chart' not in data or not data['chart']['result']:
            return None
            
        quotes = data['chart']['result'][0]['indicators']['quote'][0]
        timestamps = data['chart']['result'][0]['timestamp']
        
        df = pd.DataFrame(quotes)
        df['Date'] = pd.to_datetime(timestamps, unit='s')
        df.set_index('Date', inplace=True)
        df = df.dropna()
        return df
    except Exception as e:
        print(f"Erro ao buscar {simbolo}: {e}")
        return None

def calcular_indicadores(df):
    """Calcula indicadores técnicos manualmente (sem TA-Lib)."""
    if df is None or len(df) < 26:
        return None
    
    close = df['close']
    high = df['high']
    low = df['low']

    # Médias Móveis
    df['SMA9'] = close.rolling(window=9).mean()
    df['SMA21'] = close.rolling(window=21).mean()
    
    # RSI (14 períodos)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    exp1 = close.ewm(span=12, adjust=False).mean()
    exp2 = close.ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()

    # Estocástico (14, 3)
    low_min = low.rolling(window=14).min()
    high_max = high.rolling(window=14).max()
    df['StochK'] = 100 * (close - low_min) / (high_max - low_min)
    df['StochD'] = df['StochK'].rolling(window=3).mean()

    ultimo = df.iloc[-1]
    
    # Definir Tendência
    tendencia = "LATERAL"
    if ultimo['close'] > ultimo['SMA21'] and ultimo['SMA21'] > ultimo['SMA9']:
        tendencia = "ALTA"
    elif ultimo['close'] < ultimo['SMA21'] and ultimo['SMA21'] < ultimo['SMA9']:
        tendencia = "BAIXA"

    return {
        'preco': round(float(ultimo['close']), 2),
        'rsi': round(float(ultimo['RSI']), 2),
        'macd': round(float(ultimo['MACD']), 4),
        'macd_signal': round(float(ultimo['Signal']), 4),
        'stoch': round(float(ultimo['StochK']), 2),
        'tendencia': tendencia,
        'volume': int(ultimo['volume']),
        'atr': round(float((high - low).rolling(14).mean().iloc[-1]), 2)
    }

def analisar_ativo(simbolo):
    """Orquestra a análise de um único ativo."""
    print(f"Analisando {simbolo}...")
    df = buscar_dados_yahoo(simbolo)
    if df is None:
        return None
    
    dados = calcular_indicadores(df)
    if not dados:
        return None
    
    # Lógica de Score Simplificada
    score = 5.0
    if dados['tendencia'] == "ALTA": score += 2.0
    elif dados['tendencia'] == "BAIXA": score -= 2.0
    
    if 30 <= dados['rsi'] <= 70: score += 0.5
    if dados['rsi'] < 30: score += 1.5 # Sobrevendido
    if dados['rsi'] > 70: score -= 1.5 # Sobrecomprado
    
    if dados['macd'] > dados['macd_signal']: score += 1.0
    else: score -= 1.0
    
    # Normalizar entre 0 e 10
    score_final = min(10.0, max(0.0, score))
    
    return {
        "simbolo": simbolo,
        "dados": dados,
        "score": score_final
    }
