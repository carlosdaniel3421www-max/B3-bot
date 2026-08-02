import pandas as pd
import numpy as np
import requests

def buscar_dados_yahoo(simbolo, periodo=60):
    """Busca dados históricos no Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{simbolo}.SA"
    params = {
        "range": f"{periodo}d",
        "interval": "1d",
        "includePrePost": "false"
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
        data = resp.json()
        quotes = data['chart']['result'][0]['indicators']['quote'][0]
        df = pd.DataFrame(quotes)
        df['Date'] = pd.to_datetime(data['chart']['result'][0]['timestamp'], unit='s')
        df.set_index('Date', inplace=True)
        # Limpeza básica
        df = df.dropna()
        return df
    except Exception as e:
        print(f"Erro ao buscar {simbolo}: {e}")
        return None

def calcular_indicadores(df):
    """Calcula indicadores manualmente sem TA-Lib."""
    if df is None or len(df) < 20: return None
    
    # Preço de fechamento
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']

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

    # Estocástico (14, 3, 3)
    low_min = low.rolling(window=14).min()
    high_max = high.rolling(window=14).max()
    df['StochK'] = 100 * (close - low_min) / (high_max - low_min)
    df['StochD'] = df['StochK'].rolling(window=3).mean()

    # ADX Simplificado (Tendência)
    # Cálculo aproximado para evitar complexidade excessiva
    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    atr = tr.rolling(14).mean()
    
    # Classificação de Tendência baseada em preço vs médias
    ultimo = df.iloc[-1]
    tendencia = "LATERAL"
    if ultimo['close'] > ultimo['SMA21'] > ultimo['SMA9']:
        tendencia = "ALTA"
    elif ultimo['close'] < ultimo['SMA21'] < ultimo['SMA9']:
        tendencia = "BAIXA"

    return {
        'preco': round(ultimo['close'], 2),
        'rsi': round(ultimo['RSI'], 2),
        'macd': round(ultimo['MACD'], 4),
        'macd_signal': round(ultimo['Signal'], 4),
        'stoch': round(ultimo['StochK'], 2),
        'tendencia': tendencia,
        'volume': round(ultimo['volume'], 0),
        'atr': round(atr.iloc[-1], 2)
    }

def analisar_ativo(simbolo):
    print(f"Analisando {simbolo}...")
    df = buscar_dados_yahoo(simbolo)
    if df is None: return None
    
    dados = calcular_indicadores(df)
    if not dados: return None
    
    # Lógica de Score Simples
    score = 5.0 # Neutro
    if dados['tendencia'] == "ALTA": score += 2
    if dados['tendencia'] == "BAIXA": score -= 2
    
    if 30 <= dados['rsi'] <= 70: score += 1
    if dados['rsi'] < 30: score += 1.5 # Sobrevendido
    if dados['rsi'] > 70: score -= 1.5 # Sobrecomprado
    
    if dados['macd'] > dados['macd_signal']: score += 1
    else: score -= 1
    
    return {
        "simbolo": simbolo,
        "dados": dados,
        "score": min(10, max(0, score)) # Limita entre 0 e 10
    }
