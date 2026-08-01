"""
B3 Swing Trade Analyzer
------------------------
Analisa o gráfico de um ativo da B3 usando confluência de:
- Tendência (médias móveis: SMA9, SMA21, SMA50, SMA200)
- Suporte e resistência (pivots + máx/mín recentes)
- Osciladores (RSI, MACD, Estocástico)
- Volume e VWAP

Gera um "placar de confluência" e um gráfico com tudo marcado.

USO:
    python b3_swing_analyzer.py PETR4 --periodo 1y

Requer internet normal (roda na SUA máquina, não no sandbox do Claude).
Instale as dependências antes:
    pip install yfinance pandas numpy matplotlib

AVISO: Esta ferramenta é um apoio técnico à leitura de gráfico.
Não é recomendação de investimento. A decisão final é sempre sua.
"""

import argparse
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


# --------------------------------------------------------------------------
# 1. COLETA DE DADOS
# --------------------------------------------------------------------------

def baixar_dados(ticker: str, periodo: str = "1y", intervalo: str = "1d", tentativas: int = 3) -> pd.DataFrame:
    """
    Baixa dados históricos via yfinance. Ticker sem sufixo -> adiciona .SA (B3).
    Tenta novamente em caso de falha intermitente (comum no Yahoo Finance),
    com uma pequena pausa entre tentativas.
    """
    import time
    import yfinance as yf

    if not ticker.upper().endswith(".SA"):
        ticker = ticker.upper() + ".SA"

    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            df = yf.download(ticker, period=periodo, interval=intervalo, auto_adjust=True, progress=False)
            if not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)
                df.index.name = "date"
                return df
            ultimo_erro = "Retorno vazio"
        except Exception as e:
            ultimo_erro = str(e)

        if tentativa < tentativas:
            time.sleep(2 * tentativa)  # espera um pouco mais a cada nova tentativa

    raise ValueError(f"Não foi possível baixar dados para {ticker} após {tentativas} tentativas. Último erro: {ultimo_erro}")


# --------------------------------------------------------------------------
# 2. INDICADORES
# --------------------------------------------------------------------------

def calcular_medias_moveis(df: pd.DataFrame) -> pd.DataFrame:
    df["sma9"] = df["close"].rolling(9).mean()
    df["sma21"] = df["close"].rolling(21).mean()
    df["sma50"] = df["close"].rolling(50).mean()
    df["sma200"] = df["close"].rolling(200).mean()
    return df


def calcular_rsi(df: pd.DataFrame, periodo: int = 14) -> pd.DataFrame:
    delta = df["close"].diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()
    media_perda = perda.ewm(alpha=1 / periodo, min_periods=periodo, adjust=False).mean()
    rs = media_ganho / media_perda
    df["rsi"] = 100 - (100 / (1 + rs))
    return df


def calcular_macd(df: pd.DataFrame, rapida=12, lenta=26, sinal=9) -> pd.DataFrame:
    ema_rapida = df["close"].ewm(span=rapida, adjust=False).mean()
    ema_lenta = df["close"].ewm(span=lenta, adjust=False).mean()
    df["macd"] = ema_rapida - ema_lenta
    df["macd_sinal"] = df["macd"].ewm(span=sinal, adjust=False).mean()
    df["macd_hist"] = df["macd"] - df["macd_sinal"]
    return df


def calcular_estocastico(df: pd.DataFrame, periodo=14, suavizacao=3) -> pd.DataFrame:
    minima = df["low"].rolling(periodo).min()
    maxima = df["high"].rolling(periodo).max()
    df["stoch_k"] = 100 * (df["close"] - minima) / (maxima - minima)
    df["stoch_d"] = df["stoch_k"].rolling(suavizacao).mean()
    return df


def calcular_vwap(df: pd.DataFrame, janela: int = 20) -> pd.DataFrame:
    """VWAP móvel (aproximado, base diária) para uso em swing trade."""
    preco_tipico = (df["high"] + df["low"] + df["close"]) / 3
    pv = preco_tipico * df["volume"]
    df["vwap"] = pv.rolling(janela).sum() / df["volume"].rolling(janela).sum()
    return df


def calcular_suporte_resistencia(df: pd.DataFrame, janela: int = 20) -> pd.DataFrame:
    """Suporte/resistência simples: mínima e máxima das últimas N sessões."""
    df["resistencia"] = df["high"].rolling(janela).max()
    df["suporte"] = df["low"].rolling(janela).min()
    return df


def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.DataFrame:
    """Average True Range — usado para dimensionar stop e alvo."""
    alta_baixa = df["high"] - df["low"]
    alta_fechamento = (df["high"] - df["close"].shift()).abs()
    baixa_fechamento = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([alta_baixa, alta_fechamento, baixa_fechamento], axis=1).max(axis=1)
    df["atr"] = tr.rolling(periodo).mean()
    return df


def calcular_indicadores(df: pd.DataFrame) -> pd.DataFrame:
    df = calcular_medias_moveis(df)
    df = calcular_rsi(df)
    df = calcular_macd(df)
    df = calcular_estocastico(df)
    df = calcular_vwap(df)
    df = calcular_suporte_resistencia(df)
    df = calcular_atr(df)
    return df


def sugerir_stop_alvo(df: pd.DataFrame, direcao: str, atr_mult: float = 1.5, risco_retorno: float = 2.0,
                       risco_maximo_atr_mult: float = 3.0) -> dict:
    """
    Sugere stop-loss e alvo (take-profit) com base em ATR e suporte/resistência.
    """
    ultimo = df.iloc[-1]
    preco = ultimo["close"]
    atr = ultimo["atr"]

    if direcao == "compra":
        stop = min(ultimo["suporte"], preco - atr_mult * atr)
        piso_stop = preco - risco_maximo_atr_mult * atr  # nunca deixa o stop mais longe que isso
        stop = max(stop, piso_stop)
        risco = preco - stop
        alvo = preco + risco_retorno * risco
    else:  # venda
        stop = max(ultimo["resistencia"], preco + atr_mult * atr)
        teto_stop = preco + risco_maximo_atr_mult * atr  # nunca deixa o stop mais longe que isso
        stop = min(stop, teto_stop)
        risco = stop - preco
        alvo = preco - risco_retorno * risco

    return {
        "preco_entrada": round(preco, 2),
        "stop": round(stop, 2),
        "alvo": round(alvo, 2),
        "risco_por_acao": round(abs(risco), 2),
        "relacao_risco_retorno": f"1:{risco_retorno:g}",
    }


def projetar_volume_dia_atual(df: pd.DataFrame, hora_abertura: float = 10.0, hora_fechamento: float = 17.0) -> pd.DataFrame:
    """
    Se a última barra do df for do dia de HOJE e o pregão ainda estiver em
    andamento, projeta o volume dessa barra pro dia inteiro.
    """
    from datetime import datetime, timedelta

    if df.empty:
        return df

    agora_brt = datetime.utcnow() - timedelta(hours=3)  # Brasília = UTC-3 (sem horário de verão)
    ultima_data = df.index[-1].date()

    if ultima_data != agora_brt.date():
        return df  # última barra já é de um pregão fechado, não precisa projetar

    hora_atual = agora_brt.hour + agora_brt.minute / 60
    if hora_atual <= hora_abertura or hora_atual >= hora_fechamento:
        return df  # fora do pregão

    fracao_decorrida = max((hora_atual - hora_abertura) / (hora_fechamento - hora_abertura), 0.05)

    df = df.copy()
    df.iloc[-1, df.columns.get_loc("volume")] = df["volume"].iloc[-1] / fracao_decorrida
    return df


def avaliar_timeframe_horario(ticker: str, periodo: str = "5d") -> dict:
    """
    Leitura rápida no gráfico de 1 HORA (intradiário), usada só pelo
    relatório da tarde pra CONFIRMAR (ou contestar) o sinal de curto prazo.
    """
    try:
        df_h = baixar_dados(ticker, periodo=periodo, intervalo="60m")
    except Exception:
        return {"direcao": "indisponivel", "motivo": "Dados intradiários indisponíveis"}

    if len(df_h) < 25:
        return {"direcao": "indisponivel", "motivo": "Histórico intradiário insuficiente"}

    df_h["ema9"] = df_h["close"].ewm(span=9, adjust=False).mean()
    df_h["ema21"] = df_h["close"].ewm(span=21, adjust=False).mean()

    delta = df_h["close"].diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    media_perda = perda.ewm(alpha=1 / 14, min_periods=14, adjust=False).mean()
    rs = media_ganho / media_perda
    df_h["rsi_h"] = 100 - (100 / (1 + rs))

    ultimo = df_h.iloc[-1]
    tendencia_alta = ultimo["close"] > ultimo["ema9"] > ultimo["ema21"]
    tendencia_baixa = ultimo["close"] < ultimo["ema9"] < ultimo["ema21"]

    if tendencia_alta and ultimo["rsi_h"] > 50:
        direcao = "compra"
    elif tendencia_baixa and ultimo["rsi_h"] < 50:
        direcao = "venda"
    else:
        direcao = "neutro"

    return {
        "direcao": direcao,
        "preco": round(ultimo["close"], 2),
        "rsi_h": round(ultimo["rsi_h"], 0),
    }


def calcular_indicadores_curto_prazo(df: pd.DataFrame) -> pd.DataFrame:
    """
    Versão dos indicadores com períodos mais curtos (SMA5/10/20, RSI7,
    MACD rápido 5/13/5, Estocástico(7), suporte/resistência de 10 dias).
    """
    df["sma5_curto"] = df["close"].rolling(5).mean()
    df["sma10_curto"] = df["close"].rolling(10).mean()
    df["sma20_curto"] = df["close"].rolling(20).mean()

    delta = df["close"].diff()
    ganho = delta.clip(lower=0)
    perda = -delta.clip(upper=0)
    media_ganho = ganho.ewm(alpha=1 / 7, min_periods=7, adjust=False).mean()
    media_perda = perda.ewm(alpha=1 / 7, min_periods=7, adjust=False).mean()
    rs = media_ganho / media_perda
    df["rsi_curto"] = 100 - (100 / (1 + rs))

    ema_rapida = df["close"].ewm(span=5, adjust=False).mean()
    ema_lenta = df["close"].ewm(span=13, adjust=False).mean()
    df["macd_curto"] = ema_rapida - ema_lenta
    df["macd_sinal_curto"] = df["macd_curto"].ewm(span=5, adjust=False).mean()
    df["macd_hist_curto"] = df["macd_curto"] - df["macd_sinal_curto"]

    minima = df["low"].rolling(7).min()
    maxima = df["high"].rolling(7).max()
    df["stoch_k_curto"] = 100 * (df["close"] - minima) / (maxima - minima)

    alta_baixa = df["high"] - df["low"]
    alta_fechamento = (df["high"] - df["close"].shift()).abs()
    baixa_fechamento = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([alta_baixa, alta_fechamento, baixa_fechamento], axis=1).max(axis=1)
    df["atr_curto"] = tr.rolling(7).mean()

    df["resistencia_curta"] = df["high"].rolling(10).max()
    df["suporte_curto"] = df["low"].rolling(10).min()

    return df


def avaliar_ativo_curto_prazo(df: pd.DataFrame) -> dict:
    """
    Igual a avaliar_ativo, mas usando os indicadores de período curto
    (SMA5/10/20, RSI7, MACD 5/13/5, Estocástico7).
    """
    ultimo = df.iloc[-1]
    penultimo = df.iloc[-2] if len(df) > 1 else ultimo

    pontos_compra, pontos_venda = 0, 0
    motivos_compra, motivos_venda = [], []

    # --- 1. Regime de tendência de curtíssimo prazo — até 2 pontos ---
    em_forte_alta = ultimo["close"] > ultimo["sma5_curto"] > ultimo["sma10_curto"] > ultimo["sma20_curto"]
    em_alta = em_forte_alta or (ultimo["close"] > ultimo["sma5_curto"] > ultimo["sma10_curto"])
    em_forte_baixa = ultimo["close"] < ultimo["sma5_curto"] < ultimo["sma10_curto"] < ultimo["sma20_curto"]
    em_baixa = em_forte_baixa or (ultimo["close"] < ultimo["sma5_curto"] < ultimo["sma10_curto"])

    if em_forte_alta:
        pontos_compra += 2
        motivos_compra.append("Tendência de curtíssimo prazo de alta (preço > SMA5 > SMA10 > SMA20)")
    elif em_alta:
        pontos_compra += 1
        motivos_compra.append("Tendência de curtíssimo prazo de alta (preço > SMA5 > SMA10)")
    elif em_forte_baixa:
        pontos_venda += 2
        motivos_venda.append("Tendência de curtíssimo prazo de baixa (preço < SMA5 < SMA10 < SMA20)")
    elif em_baixa:
        pontos_venda += 1
        motivos_venda.append("Tendência de curtíssimo prazo de baixa (preço < SMA5 < SMA10)")

    # --- 2. RSI(7) — interpretação depende do regime ---
    rsi = ultimo["rsi_curto"]
    if em_alta:
        if rsi > 70:
            pontos_compra += 2
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — momentum forte dentro da tendência de alta")
        elif rsi < 40:
            pts = 2 if rsi < 30 else 1
            pontos_compra += pts
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — recuo dentro da tendência de alta")
    elif em_baixa:
        if rsi < 30:
            pontos_venda += 2
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — momentum forte dentro da tendência de baixa")
        elif rsi > 60:
            pts = 2 if rsi > 70 else 1
            pontos_venda += pts
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — repique dentro da tendência de baixa")
    else:
        if rsi < 30:
            pontos_compra += 2
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — sobrevenda em lateral de curto prazo")
        elif rsi < 40:
            pontos_compra += 1
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — zona de sobrevenda")
        elif rsi > 70:
            pontos_venda += 2
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — sobrecompra em lateral de curto prazo")
        elif rsi > 60:
            pontos_venda += 1
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — zona de sobrecompra")

    # --- 3. MACD rápido (5/13/5) — momentum direcional puro ---
    atr_curto = ultimo["atr_curto"] if pd.notna(ultimo["atr_curto"]) else 0
    diff_macd = ultimo["macd_curto"] - ultimo["macd_sinal_curto"]
    zona_morta_macd = 0.05 * atr_curto if atr_curto > 0 else 0
    hist_cresceu = ultimo["macd_hist_curto"] > penultimo["macd_hist_curto"]

    if abs(diff_macd) < zona_morta_macd:
        pass
    elif diff_macd > 0:
        pts = 2 if hist_cresceu else 1
        pontos_compra += pts
        extra = " e ganhando força" if hist_cresceu else ""
        motivos_compra.append(f"MACD rápido (5/13/5) acima do sinal (momentum comprador{extra})")
    else:
        pts = 2 if not hist_cresceu else 1
        pontos_venda += pts
        extra = " e perdendo força" if not hist_cresceu else ""
        motivos_venda.append(f"MACD rápido (5/13/5) abaixo do sinal (momentum vendedor{extra})")

    # --- 4. Estocástico(7) — mesma lógica condicional ---
    stoch = ultimo["stoch_k_curto"]
    if em_alta:
        if stoch > 80:
            pontos_compra += 2
            motivos_compra.append(f"Estocástico(7) em {stoch:.0f} — momentum forte, compatível com tendência de alta")
        elif stoch < 35:
            pts = 2 if stoch < 20 else 1
            pontos_compra += pts
            motivos_compra.append(f"Estocástico(7) em {stoch:.0f} — recuo dentro da tendência de alta")
    elif em_baixa:
        if stoch < 20:
            pontos_venda += 2
            motivos_venda.append(f"Estocástico(7) em {stoch:.0f} — momentum forte, compatível com tendência de baixa")
        elif stoch > 65:
            pts = 2 if stoch > 80 else 1
            pontos_venda += pts
            motivos_venda.append(f"Estocástico(7) em {stoch:.0f} — repique dentro da tendência de baixa")
    else:
        if stoch < 20:
            pontos_compra += 2
            motivos_compra.append(f"Estocástico(7) em {stoch:.0f} — sobrevenda extrema em lateral")
        elif stoch < 35:
            pontos_compra += 1
            motivos_compra.append(f"Estocástico(7) em {stoch:.0f} — sobrevenda")
        elif stoch > 80:
            pontos_venda += 2
            motivos_venda.append(f"Estocástico(7) em {stoch:.0f} — sobrecompra extrema em lateral")
        elif stoch > 65:
            pontos_venda += 1
            motivos_venda.append(f"Estocástico(7) em {stoch:.0f} — sobrecompra")

    # --- 5. Suporte/Resistência de 10 dias — distingue rompimento de toque ---
    resistencia_anterior = penultimo["resistencia_curta"]
    suporte_anterior = penultimo["suporte_curto"]
    media_volume = df["volume"].rolling(10).mean().iloc[-1]
    volume_alto = ultimo["volume"] > media_volume

    rompeu_resistencia = ultimo["close"] > resistencia_anterior
    rompeu_suporte = ultimo["close"] < suporte_anterior

    faixa = ultimo["resistencia_curta"] - ultimo["suporte_curto"]
    if faixa > 0:
        dist_suporte = (ultimo["close"] - ultimo["suporte_curto"]) / faixa

        if dist_suporte > 0.85:
            if em_alta:
                if rompeu_resistencia:
                    pts = 2 if volume_alto else 1
                    extra = " com volume acima da média (rompimento confirmado)" if volume_alto else ""
                    motivos_compra.append(f"Rompendo a máxima de 10 dias{extra}")
                else:
                    pts = 1
                    motivos_compra.append("Sustentando perto da máxima de 10 dias dentro da tendência de alta")
                pontos_compra += pts
            else:
                pts = 2 if volume_alto else 1
                pontos_venda += pts
                extra = " com volume acima da média" if volume_alto else ""
                motivos_venda.append(f"Testando resistência de 10 dias sem tendência de alta{extra} — risco de rejeição")
        elif dist_suporte < 0.15:
            if em_baixa:
                if rompeu_suporte:
                    pts = 2 if volume_alto else 1
                    extra = " com volume acima da média (rompimento confirmado)" if volume_alto else ""
                    motivos_venda.append(f"Rompendo a mínima de 10 dias{extra}")
                else:
                    pts = 1
                    motivos_venda.append("Sustentando perto da mínima de 10 dias dentro da tendência de baixa")
                pontos_venda += pts
            else:
                pts = 2 if volume_alto else 1
                pontos_compra += pts
                extra = " com volume acima da média" if volume_alto else ""
                motivos_compra.append(f"Testando suporte de 10 dias sem tendência de baixa{extra} — possível compra")

    if pontos_compra == pontos_venda:
        direcao = "neutro"
        score = pontos_compra
        motivos = (motivos_compra + motivos_venda) or ["Nenhum indicador de curto prazo com sinal relevante"]
    elif pontos_compra > pontos_venda:
        direcao = "compra"
        score = pontos_compra
        motivos = motivos_compra
    else:
        direcao = "venda"
        score = pontos_venda
        motivos = motivos_venda

    return {
        "direcao": direcao,
        "score": score,
        "motivos": motivos,
        "preco_atual": ultimo["close"],
        "data": df.index[-1],
    }


# --------------------------------------------------------------------------
# 3. PLACAR DE CONFLUÊNCIA (Atualizado para pesos de Swing Trade Profissional)
# --------------------------------------------------------------------------

def avaliar_ativo(df: pd.DataFrame) -> dict:
    """
    Avalia o ativo com placar de 0 a 10 usando pesos profissionais de Swing Trade.
    Distribuição: Tendência (4 pts) + Momentum/Gatilho (4 pts) + Volume/Contexto (2 pts).
    """
    ultimo = df.iloc[-1]
    penultimo = df.iloc[-2] if len(df) > 1 else ultimo

    pontos_compra, pontos_venda = 0, 0
    motivos_compra, motivos_venda = [], []

    # --- 1. TENDÊNCIA E ALINHAMENTO (Até 4 pontos) ---
    tendencia_alta_media = ultimo["sma21"] > ultimo["sma50"]
    tendencia_baixa_media = ultimo["sma21"] < ultimo["sma50"]

    if tendencia_alta_media:
        pontos_compra += 2
        motivos_compra.append("Tendência de alta primária (SMA21 > SMA50)")
        if ultimo["close"] > ultimo["sma21"]:
            pontos_compra += 1
            motivos_compra.append("Preço trabalhando acima da SMA21")
        if ultimo["sma9"] > ultimo["sma21"]:
            pontos_compra += 1
            motivos_compra.append("Alinhamento direcional de curto prazo (SMA9 > SMA21)")
            
    elif tendencia_baixa_media:
        pontos_venda += 2
        motivos_venda.append("Tendência de baixa primária (SMA21 < SMA50)")
        if ultimo["close"] < ultimo["sma21"]:
            pontos_venda += 1
            motivos_venda.append("Preço trabalhando abaixo da SMA21")
        if ultimo["sma9"] < ultimo["sma21"]:
            pontos_venda += 1
            motivos_venda.append("Alinhamento direcional de curto prazo (SMA9 < SMA21)")

    # --- 2. GATILHOS DE MOMENTUM: MACD E RSI (Até 4 pontos) ---
    # MACD (2 pontos diretos)
    if ultimo["macd"] > ultimo["macd_sinal"]:
        pontos_compra += 2
        motivos_compra.append("MACD comprador (linha MACD acima do Sinal)")
    elif ultimo["macd"] < ultimo["macd_sinal"]:
        pontos_venda += 2
        motivos_venda.append("MACD vendedor (linha MACD abaixo do Sinal)")

    # RSI (2 pontos) - Valorizamos zonas saudáveis (45 a 65) e de recuo (perto de 40)
    rsi = ultimo["rsi"]
    if 40 <= rsi <= 68:
        pontos_compra += 2
        motivos_compra.append(f"RSI em {rsi:.0f} — Momentum saudável, espaço para alta")
    elif rsi > 68:
        pontos_compra += 1
        motivos_compra.append(f"RSI em {rsi:.0f} — Tendência forte, mas próximo de sobrecompra")

    if 32 <= rsi <= 60:
        pontos_venda += 2
        motivos_venda.append(f"RSI em {rsi:.0f} — Momentum saudável, espaço para queda")
    elif rsi < 32:
        pontos_venda += 1
        motivos_venda.append(f"RSI em {rsi:.0f} — Tendência forte, mas próximo de sobrevenda")

    # --- 3. VOLUME E CONTEXTO DE PREÇO (Até 2 pontos) ---
    # Volume (1 ponto)
    media_volume = df["volume"].rolling(20).mean().iloc[-1]
    if ultimo["volume"] > media_volume:
        pontos_compra += 1
        pontos_venda += 1
        motivos_compra.append("Volume financeiro acima da média de 20 dias")
        motivos_venda.append("Volume financeiro acima da média de 20 dias")

    # Contexto (1 ponto) - Onde o preço está no canal?
    faixa = ultimo["resistencia"] - ultimo["suporte"]
    if faixa > 0:
        dist_suporte = (ultimo["close"] - ultimo["suporte"]) / faixa
        if dist_suporte > 0.8:
            pontos_compra += 1
            motivos_compra.append("Rompendo ou pressionando resistência recente")
        elif 0.3 <= dist_suporte <= 0.6 and tendencia_alta_media:
            pontos_compra += 1
            motivos_compra.append("Pullback saudável: Preço em zona de valor e respiro")
            
        if dist_suporte < 0.2:
            pontos_venda += 1
            motivos_venda.append("Perdendo ou pressionando suporte recente")
        elif 0.4 <= dist_suporte <= 0.7 and tendencia_baixa_media:
            pontos_venda += 1
            motivos_venda.append("Repique saudável: Preço em zona de valor para venda")

    # --- CÁLCULO FINAL ---
    if pontos_compra == pontos_venda:
        direcao = "neutro"
        score = pontos_compra
        motivos = (motivos_compra + motivos_venda) or ["Nenhum indicador com sinal direcional forte"]
    elif pontos_compra > pontos_venda:
        direcao = "compra"
        score = min(10, pontos_compra)
        motivos = motivos_compra
    else:
        direcao = "venda"
        score = min(10, pontos_venda)
        motivos = motivos_venda

    return {
        "direcao": direcao,
        "score": score,
        "motivos": motivos,
        "preco_atual": ultimo["close"],
        "data": df.index[-1],
    }


# --------------------------------------------------------------------------
# 4. GRÁFICO
# --------------------------------------------------------------------------

def plotar_grafico(df: pd.DataFrame, ticker: str, caminho_saida: str):
    fig, eixos = plt.subplots(
        4, 1, figsize=(14, 12), sharex=True,
        gridspec_kw={"height_ratios": [3, 1, 1, 1]}
    )
    ax_preco, ax_vol, ax_rsi_stoch, ax_macd = eixos

    # --- Preço + médias + suporte/resistência ---
    ax_preco.plot(df.index, df["close"], label="Fechamento", color="black", linewidth=1.2)
    ax_preco.plot(df.index, df["sma9"], label="SMA9", color="#1f77b4", linewidth=0.9)
    ax_preco.plot(df.index, df["sma21"], label="SMA21", color="#ff7f0e", linewidth=0.9)
    ax_preco.plot(df.index, df["sma50"], label="SMA50", color="#2ca02c", linewidth=0.9)
    ax_preco.plot(df.index, df["sma200"], label="SMA200", color="#d62728", linewidth=0.9)
    ax_preco.plot(df.index, df["vwap"], label="VWAP (20)", color="purple", linewidth=0.8, linestyle="--")
    ax_preco.plot(df.index, df["resistencia"], label="Resistência (20d)", color="red", linewidth=0.7, linestyle=":")
    ax_preco.plot(df.index, df["suporte"], label="Suporte (20d)", color="green", linewidth=0.7, linestyle=":")
    ax_preco.set_title(f"{ticker} — Análise Técnica (Swing Trade)")
    ax_preco.legend(loc="upper left", fontsize=8, ncol=4)
    ax_preco.grid(alpha=0.3)

    # --- Volume ---
    cores_vol = np.where(df["close"] >= df["close"].shift(1), "green", "red")
    ax_vol.bar(df.index, df["volume"], color=cores_vol, alpha=0.6, width=1)
    ax_vol.set_ylabel("Volume")
    ax_vol.grid(alpha=0.3)

    # --- RSI + Estocástico ---
    ax_rsi_stoch.plot(df.index, df["rsi"], label="RSI(14)", color="blue", linewidth=0.9)
    ax_rsi_stoch.plot(df.index, df["stoch_k"], label="%K Estocástico", color="orange", linewidth=0.7)
    ax_rsi_stoch.axhline(70, color="red", linestyle="--", linewidth=0.6)
    ax_rsi_stoch.axhline(30, color="green", linestyle="--", linewidth=0.6)
    ax_rsi_stoch.set_ylabel("RSI / Estocástico")
    ax_rsi_stoch.legend(loc="upper left", fontsize=8)
    ax_rsi_stoch.grid(alpha=0.3)

    # --- MACD ---
    ax_macd.plot(df.index, df["macd"], label="MACD", color="blue", linewidth=0.9)
    ax_macd.plot(df.index, df["macd_sinal"], label="Sinal", color="orange", linewidth=0.9)
    cores_hist = np.where(df["macd_hist"] >= 0, "green", "red")
    ax_macd.bar(df.index, df["macd_hist"], color=cores_hist, alpha=0.5, width=1)
    ax_macd.set_ylabel("MACD")
    ax_macd.legend(loc="upper left", fontsize=8)
    ax_macd.grid(alpha=0.3)

    ax_macd.xaxis.set_major_formatter(mdates.DateFormatter("%b/%y"))
    plt.tight_layout()
    plt.savefig(caminho_saida, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------
# 5. MAIN
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Analisador técnico de ações da B3 para swing trade")
    parser.add_argument("ticker", help="Código do ativo, ex: PETR4, VALE3, ITSA4")
    parser.add_argument("--periodo", default="1y", help="Período do histórico (ex: 6mo, 1y, 2y)")
    parser.add_argument("--saida", default=None, help="Caminho do arquivo de imagem de saída")
    args = parser.parse_args()

    print(f"Baixando dados de {args.ticker}...")
    df = baixar_dados(args.ticker, periodo=args.periodo)

    print("Calculando indicadores...")
    df = calcular_indicadores(df)

    avaliacao = avaliar_ativo(df)

    print("\n" + "=" * 60)
    print(f"ATIVO: {args.ticker.upper()}  |  DATA: {avaliacao['data'].date()}")
    print(f"PREÇO ATUAL: R$ {avaliacao['preco_atual']:.2f}")
    print(f"NÍVEL: {avaliacao['score']}/10 — {avaliacao['direcao'].upper()}")
    print("-" * 60)
    print("Motivos considerados:")
    for m in avaliacao["motivos"]:
        print(f"  • {m}")
    print("=" * 60)
    print("\nAVISO: Ferramenta de apoio técnico, não é recomendação de")
    print("investimento. Sempre valide com sua própria análise de risco.\n")

    caminho_saida = args.saida or f"{args.ticker.upper()}_analise.png"
    plotar_grafico(df, args.ticker.upper(), caminho_saida)
    print(f"Gráfico salvo em: {caminho_saida}")


if __name__ == "__main__":
    main()
