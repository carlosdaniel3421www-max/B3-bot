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
    direcao: "compra" ou "venda"
    atr_mult: quantos ATRs de folga o stop deixa além do suporte/resistência
              (menor = stop mais apertado, adequado pra prazo mais curto)
    risco_retorno: múltiplo do risco usado pra definir o alvo (2.0 = alvo a 2x
                   a distância do stop; menor = alvo mais perto, atingido mais rápido)
    risco_maximo_atr_mult: TETO de risco por ação, em múltiplos de ATR. Evita que
                   ativos em forte tendência (onde o suporte/resistência de 20 dias
                   fica muito longe do preço) gerem stops enormes e desproporcionais.
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
    andamento, projeta o volume dessa barra pro dia inteiro (baseado na
    fração de tempo já decorrida do pregão), pra não subestimar comparações
    de volume (ex: "volume acima da média") por causa de um candle parcial.

    Isso é relevante pro relatório da tarde (13h): nesse horário, o candle
    de hoje só tem ~3h de volume acumulado, e comparar isso direto com a
    média de 20 dias (candles completos) tende a dar falso negativo.

    É uma estimativa grosseira (assume volume distribuído uniformemente ao
    longo do pregão, o que raramente é exato — B3 costuma ter mais volume
    na abertura e no fechamento) — melhor que ignorar o problema, mas não é
    uma correção perfeita.
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
    relatório da tarde pra CONFIRMAR (ou contestar) o sinal de curto prazo
    calculado no gráfico diário. Não é usada pelo relatório da manhã.

    Lógica simples: tendência via EMA9 x EMA21 no horário + RSI(14) horário
    confirmando o lado. Se não bater os dois, fica "neutro" (sem força
    suficiente pra confirmar nada).
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
    MACD rápido 5/13/5, Estocástico(7), suporte/resistência de 10 dias),
    pensada pra decisões de poucos dias (ex: relatório da tarde, foco
    "até o fim da semana"). Grava em colunas com sufixo _curto pra não
    conflitar com os indicadores padrão (usados no gráfico e no relatório
    da manhã).
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
    Versão de curtíssimo prazo da avaliação, usando indicadores com períodos menores
    (SMA5/10/20, RSI7, MACD 5/13/5, Estocástico7). Mesma lógica profissional de
    pontuação ponderada da versão padrão.
    
    Foco: decisões de poucos dias (ex: relatório da tarde, "até o fim da semana").
    """
    ultimo = df.iloc[-1]
    penultimo = df.iloc[-2] if len(df) > 1 else ultimo
    antes_penultimo = df.iloc[-3] if len(df) > 2 else penultimo

    pontos_compra, pontos_venda = 0.0, 0.0
    motivos_compra, motivos_venda = [], []
    
    # =========================================================================
    # 1. TENDÊNCIA DE CURTÍSSIMO PRAZO (até 3 pontos)
    # =========================================================================
    tendencia_muito_forte_alta = (
        ultimo["close"] > ultimo["sma5_curto"] > ultimo["sma10_curto"] > ultimo["sma20_curto"]
        and ultimo["sma5_curto"] > penultimo["sma5_curto"]
    )
    tendencia_forte_alta = (
        ultimo["close"] > ultimo["sma10_curto"] > ultimo["sma20_curto"]
        and ultimo["sma10_curto"] > penultimo["sma10_curto"]
    )
    tendencia_fraca_alta = ultimo["close"] > ultimo["sma20_curto"]
    
    tendencia_muito_forte_baixa = (
        ultimo["close"] < ultimo["sma5_curto"] < ultimo["sma10_curto"] < ultimo["sma20_curto"]
        and ultimo["sma5_curto"] < penultimo["sma5_curto"]
    )
    tendencia_forte_baixa = (
        ultimo["close"] < ultimo["sma10_curto"] < ultimo["sma20_curto"]
        and ultimo["sma10_curto"] < penultimo["sma10_curto"]
    )
    tendencia_fraca_baixa = ultimo["close"] < ultimo["sma20_curto"]

    if tendencia_muito_forte_alta:
        pontos_compra += 3.0
        motivos_compra.append("Tendência MUITO FORTE de alta (preço > SMA5 > SMA10 > SMA20)")
    elif tendencia_forte_alta:
        pontos_compra += 2.0
        motivos_compra.append("Tendência FORTE de alta (preço > SMA10 > SMA20)")
    elif tendencia_fraca_alta:
        pontos_compra += 1.0
        motivos_compra.append("Tendência FRACA de alta (preço acima da SMA20)")
    elif tendencia_muito_forte_baixa:
        pontos_venda += 3.0
        motivos_venda.append("Tendência MUITO FORTE de baixa (preço < SMA5 < SMA10 < SMA20)")
    elif tendencia_forte_baixa:
        pontos_venda += 2.0
        motivos_venda.append("Tendência FORTE de baixa (preço < SMA10 < SMA20)")
    elif tendencia_fraca_baixa:
        pontos_venda += 1.0
        motivos_venda.append("Tendência FRACA de baixa (preço abaixo da SMA20)")
    else:
        motivos_compra.append("Mercado lateral/indefinido no curtíssimo prazo")

    # =========================================================================
    # 2. MOMENTUM RSI(7) (até 2.5 pontos)
    # =========================================================================
    rsi = ultimo["rsi_curto"]
    rsi_subindo = rsi > penultimo["rsi_curto"]
    rsi_descendo = rsi < penultimo["rsi_curto"]
    
    if tendencia_forte_alta or tendencia_muito_forte_alta:
        if rsi > 60 and rsi_subindo:
            pontos_compra += 2.5
            motivos_compra.append(f"RSI(7) em {rsi:.0f} SUBINDO — momentum forte")
        elif rsi > 50:
            pontos_compra += 1.5
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — zona neutra/alta")
        elif rsi < 40 and rsi > 25:
            pontos_compra += 2.0
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — recuo saudável (oportunidade)")
        elif rsi < 25:
            pontos_compra += 1.0
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — sobrevenda extrema")
    elif tendencia_forte_baixa or tendencia_muito_forte_baixa:
        if rsi < 40 and rsi_descendo:
            pontos_venda += 2.5
            motivos_venda.append(f"RSI(7) em {rsi:.0f} DESCENDO — momentum forte")
        elif rsi < 50:
            pontos_venda += 1.5
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — zona neutra/baixa")
        elif rsi > 60 and rsi < 75:
            pontos_venda += 2.0
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — repique (oportunidade de venda)")
        elif rsi > 75:
            pontos_venda += 1.0
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — sobrecompra extrema")
    else:
        if rsi < 25:
            pontos_compra += 2.5
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — sobrevenda EXTREMA em lateral")
        elif rsi < 35:
            pontos_compra += 1.5
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — sobrevenda em lateral")
        elif rsi > 75:
            pontos_venda += 2.5
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — sobrecompra EXTREMA em lateral")
        elif rsi > 65:
            pontos_venda += 1.5
            motivos_venda.append(f"RSI(7) em {rsi:.0f} — sobrecompra em lateral")
        else:
            motivos_compra.append(f"RSI(7) em {rsi:.0f} — zona neutra")

    # =========================================================================
    # 3. MOMENTUM MACD RÁPIDO (até 2 pontos)
    # =========================================================================
    macd = ultimo["macd_curto"]
    macd_sinal = ultimo["macd_sinal_curto"]
    macd_hist = ultimo["macd_hist_curto"]
    macd_hist_ant = penultimo["macd_hist_curto"]
    macd_hist_antes = antes_penultimo["macd_hist_curto"]
    
    cruzou_compra = (penultimo["macd_curto"] <= penultimo["macd_sinal_curto"] 
                     and macd > macd_sinal)
    cruzou_venda = (penultimo["macd_curto"] >= penultimo["macd_sinal_curto"] 
                    and macd < macd_sinal)
    
    hist_acelerando_compra = macd_hist > macd_hist_ant > macd_hist_antes
    hist_acelerando_venda = macd_hist < macd_hist_ant < macd_hist_antes
    
    atr_curto = ultimo["atr_curto"] if pd.notna(ultimo["atr_curto"]) else 0
    zona_morta = 0.03 * atr_curto if atr_curto > 0 else 0.001
    diff_macd = macd - macd_sinal

    if cruzou_compra:
        pontos_compra += 2.0
        motivos_compra.append("MACD rápido CRUZOU pra cima (mudança de momentum)")
    elif cruzou_venda:
        pontos_venda += 2.0
        motivos_venda.append("MACD rápido CRUZOU pra baixo (mudança de momentum)")
    elif diff_macd > zona_morta:
        if hist_acelerando_compra:
            pontos_compra += 1.5
            motivos_compra.append("MACD rápido acima do sinal e ACELERANDO")
        else:
            pontos_compra += 0.5
            motivos_compra.append("MACD rápido acima do sinal (sem aceleração)")
    elif diff_macd < -zona_morta:
        if hist_acelerando_venda:
            pontos_venda += 1.5
            motivos_venda.append("MACD rápido abaixo do sinal e ACELERANDO")
        else:
            pontos_venda += 0.5
            motivos_venda.append("MACD rápido abaixo do sinal (sem aceleração)")

    # =========================================================================
    # 4. ESTOCÁSTICO(7) (até 1.5 pontos)
    # =========================================================================
    stoch_k = ultimo["stoch_k_curto"]
    stoch_d = df["stoch_d_curto"].iloc[-1] if "stoch_d_curto" in df.columns else stoch_k
    stoch_k_ant = penultimo["stoch_k_curto"]
    
    stoch_cruzou_compra = stoch_k_ant < stoch_d and stoch_k > stoch_d and stoch_k < 40
    stoch_cruzou_venda = stoch_k_ant > stoch_d and stoch_k < stoch_d and stoch_k > 60
    
    if tendencia_forte_alta or tendencia_muito_forte_alta:
        if stoch_k > 80 and stoch_k > stoch_k_ant:
            pontos_compra += 1.5
            motivos_compra.append(f"Estocástico(7) em {stoch_k:.0f} — momentum forte")
        elif stoch_k < 40 and stoch_k > stoch_k_ant:
            pontos_compra += 1.0
            motivos_compra.append(f"Estocástico(7) em {stoch_k:.0f} — recuo terminando")
        elif stoch_cruzou_compra:
            pontos_compra += 1.0
            motivos_compra.append(f"Estocástico(7) cruzou pra cima em {stoch_k:.0f}")
    elif tendencia_forte_baixa or tendencia_muito_forte_baixa:
        if stoch_k < 20 and stoch_k < stoch_k_ant:
            pontos_venda += 1.5
            motivos_venda.append(f"Estocástico(7) em {stoch_k:.0f} — momentum forte")
        elif stoch_k > 60 and stoch_k < stoch_k_ant:
            pontos_venda += 1.0
            motivos_venda.append(f"Estocástico(7) em {stoch_k:.0f} — repique terminando")
        elif stoch_cruzou_venda:
            pontos_venda += 1.0
            motivos_venda.append(f"Estocástico(7) cruzou pra baixo em {stoch_k:.0f}")
    else:
        if stoch_k < 20 and stoch_k > stoch_k_ant:
            pontos_compra += 1.5
            motivos_compra.append(f"Estocástico(7) em {stoch_k:.0f} — saindo de sobrevenda")
        elif stoch_k > 80 and stoch_k < stoch_k_ant:
            pontos_venda += 1.5
            motivos_venda.append(f"Estocástico(7) em {stoch_k:.0f} — saindo de sobrecompra")
        elif stoch_cruzou_compra:
            pontos_compra += 0.5
            motivos_compra.append(f"Estocástico(7) cruzou pra cima")
        elif stoch_cruzou_venda:
            pontos_venda += 0.5
            motivos_venda.append(f"Estocástico(7) cruzou pra baixo")

    # =========================================================================
    # 5. VOLUME E ROMPIMENTOS (até 1.5 pontos BÔNUS)
    # =========================================================================
    volume_atual = ultimo["volume"]
    media_volume_10 = df["volume"].rolling(10).mean().iloc[-1]
    volume_alto = volume_atual > media_volume_10 * 1.3
    
    resistencia_ant = penultimo["resistencia_curta"]
    suporte_ant = penultimo["suporte_curto"]
    preco = ultimo["close"]
    
    rompeu_resistencia = preco > resistencia_ant and penultimo["close"] <= resistencia_ant
    rompeu_suporte = preco < suporte_ant and penultimo["close"] >= suporte_ant
    
    if rompeu_resistencia and volume_alto:
        pontos_compra += 1.5
        motivos_compra.append(f"ROMPIMENTO DE RESISTÊNCIA COM VOLUME ALTO")
    elif rompeu_resistencia:
        pontos_compra += 0.5
        motivos_compra.append(f"Rompendo resistência mas volume fraco")
    elif rompeu_suporte and volume_alto:
        pontos_venda += 1.5
        motivos_venda.append(f"ROMPIMENTO DE SUPORTE COM VOLUME ALTO")
    elif rompeu_suporte:
        pontos_venda += 0.5
        motivos_venda.append(f"Rompendo suporte mas volume fraco")

    # =========================================================================
    # 6. BÔNUS DE CONFLUÊNCIA (até 1 ponto extra)
    # =========================================================================
    if pontos_compra >= 4 and pontos_venda == 0:
        pontos_compra += 1.0
        motivos_compra.append("BÔNUS: Todos indicadores alinhados (confluência máxima)")
    elif pontos_venda >= 4 and pontos_compra == 0:
        pontos_venda += 1.0
        motivos_venda.append("BÔNUS: Todos indicadores alinhados (confluência máxima)")

    # =========================================================================
    # DECISÃO FINAL
    # =========================================================================
    pontos_compra = round(pontos_compra, 1)
    pontos_venda = round(pontos_venda, 1)
    
    if abs(pontos_compra - pontos_venda) < 0.5:
        direcao = "neutro"
        score = max(pontos_compra, pontos_venda)
        motivos = (motivos_compra + motivos_venda) or ["Sem sinal claro no curtíssimo prazo"]
    elif pontos_compra > pontos_venda:
        direcao = "compra"
        score = pontos_compra
        motivos = motivos_compra
    else:
        direcao = "venda"
        score = pontos_venda
        motivos = motivos_venda

    if score == 0 and motivos:
        score = 0.5

    return {
        "direcao": direcao,
        "score": min(score, 10),
        "motivos": motivos,
        "pontos_compra_detalhados": pontos_compra,
        "pontos_venda_detalhados": pontos_venda,
        "preco_atual": float(ultimo["close"]),
        "data": df.index[-1],
    }


# --------------------------------------------------------------------------
# 3. PLACAR DE CONFLUÊNCIA (heurística simples, não é garantia de nada)
# --------------------------------------------------------------------------

def avaliar_ativo(df: pd.DataFrame) -> dict:
    """
    Avalia o ativo com placar de 0 a 10 usando sistema de pontuação ponderado.
    
    LÓGICA DE PONTUAÇÃO PROFISSIONAL:
    - Cada categoria vale pontos específicos (não é simples contagem binária)
    - Tendência forte vale mais que tendência fraca
    - Confluência de indicadores na mesma direção dá bônus
    - Divergências entre indicadores reduzem a pontuação
    
    PONTO CRÍTICO: RSI/Estocástico esticados em tendência NÃO são reversão,
    são confirmação de momentum. Só indicam reversão em mercado lateral.
    """
    ultimo = df.iloc[-1]
    penultimo = df.iloc[-2] if len(df) > 1 else ultimo
    antes_penultimo = df.iloc[-3] if len(df) > 2 else penultimo

    pontos_compra, pontos_venda = 0.0, 0.0
    motivos_compra, motivos_venda = [], []
    
    # =========================================================================
    # 1. TENDÊNCIA PRIMÁRIA (até 3 pontos) - O fator MAIS importante
    # =========================================================================
    # Tendência MUITO forte: preço > SMA9 > SMA21 > SMA50 > SMA200
    tendencia_muito_forte_alta = (
        ultimo["close"] > ultimo["sma9"] > ultimo["sma21"] > ultimo["sma50"] > ultimo["sma200"]
        and ultimo["sma9"] > penultimo["sma9"]  # SMA9 ascendente
    )
    tendencia_forte_alta = (
        ultimo["close"] > ultimo["sma21"] > ultimo["sma50"]
        and ultimo["sma21"] > penultimo["sma21"]
    )
    tendencia_fraca_alta = ultimo["close"] > ultimo["sma50"]
    
    tendencia_muito_forte_baixa = (
        ultimo["close"] < ultimo["sma9"] < ultimo["sma21"] < ultimo["sma50"] < ultimo["sma200"]
        and ultimo["sma9"] < penultimo["sma9"]
    )
    tendencia_forte_baixa = (
        ultimo["close"] < ultimo["sma21"] < ultimo["sma50"]
        and ultimo["sma21"] < penultimo["sma21"]
    )
    tendencia_fraca_baixa = ultimo["close"] < ultimo["sma50"]

    if tendencia_muito_forte_alta:
        pontos_compra += 3.0
        motivos_compra.append("Tendência MUITO FORTE de alta (preço > SMA9 > SMA21 > SMA50 > SMA200, todas ascendentes)")
    elif tendencia_forte_alta:
        pontos_compra += 2.0
        motivos_compra.append("Tendência FORTE de alta (preço > SMA21 > SMA50, médias ascendentes)")
    elif tendencia_fraca_alta:
        pontos_compra += 1.0
        motivos_compra.append("Tendência FRACA de alta (preço acima da SMA50)")
    elif tendencia_muito_forte_baixa:
        pontos_venda += 3.0
        motivos_venda.append("Tendência MUITO FORTE de baixa (preço < SMA9 < SMA21 < SMA50 < SMA200, todas descendentes)")
    elif tendencia_forte_baixa:
        pontos_venda += 2.0
        motivos_venda.append("Tendência FORTE de baixa (preço < SMA21 < SMA50, médias descendentes)")
    elif tendencia_fraca_baixa:
        pontos_venda += 1.0
        motivos_venda.append("Tendência FRACA de baixa (preço abaixo da SMA50)")
    else:
        motivos_compra.append("Mercado lateral/indefinido nas médias móveis")

    # =========================================================================
    # 2. MOMENTUM RSI (até 2.5 pontos) - Interpretação depende da tendência
    # =========================================================================
    rsi = ultimo["rsi"]
    rsi_subindo = rsi > penultimo["rsi"]
    rsi_descendo = rsi < penultimo["rsi"]
    
    if tendencia_forte_alta or tendencia_muito_forte_alta:
        # Em tendência de alta: RSI alto = força, RSI baixo = oportunidade de compra
        if rsi > 60 and rsi_subindo:
            pontos_compra += 2.5
            motivos_compra.append(f"RSI em {rsi:.0f} SUBINDO — momentum forte compatível com tendência de alta")
        elif rsi > 50:
            pontos_compra += 1.5
            motivos_compra.append(f"RSI em {rsi:.0f} — zona neutra/alta, consistente com tendência de alta")
        elif rsi < 40 and rsi > 25:
            pontos_compra += 2.0
            motivos_compra.append(f"RSI em {rsi:.0f} — recuo saudável dentro da tendência (oportunidade de compra)")
        elif rsi < 25:
            pontos_compra += 1.0
            motivos_compra.append(f"RSI em {rsi:.0f} — sobrevenda extrema, mas tendência primária ainda é de alta")
    elif tendencia_forte_baixa or tendencia_muito_forte_baixa:
        # Em tendência de baixa: RSI baixo = força vendedora, RSI alto = repique pra vender
        if rsi < 40 and rsi_descendo:
            pontos_venda += 2.5
            motivos_venda.append(f"RSI em {rsi:.0f} DESCENDO — momentum forte compatível com tendência de baixa")
        elif rsi < 50:
            pontos_venda += 1.5
            motivos_venda.append(f"RSI em {rsi:.0f} — zona neutra/baixa, consistente com tendência de baixa")
        elif rsi > 60 and rsi < 75:
            pontos_venda += 2.0
            motivos_venda.append(f"RSI em {rsi:.0f} — repique dentro da tendência de baixa (oportunidade de venda)")
        elif rsi > 75:
            pontos_venda += 1.0
            motivos_venda.append(f"RSI em {rsi:.0f} — sobrecompra extrema, mas tendência primária ainda é de baixa")
    else:
        # Mercado lateral: vale reversão à média clássica
        if rsi < 25:
            pontos_compra += 2.5
            motivos_compra.append(f"RSI em {rsi:.0f} — sobrevenda EXTREMA em mercado lateral (forte sinal de compra)")
        elif rsi < 35:
            pontos_compra += 1.5
            motivos_compra.append(f"RSI em {rsi:.0f} — sobrevenda em mercado lateral")
        elif rsi > 75:
            pontos_venda += 2.5
            motivos_venda.append(f"RSI em {rsi:.0f} — sobrecompra EXTREMA em mercado lateral (forte sinal de venda)")
        elif rsi > 65:
            pontos_venda += 1.5
            motivos_venda.append(f"RSI em {rsi:.0f} — sobrecompra em mercado lateral")
        else:
            motivos_compra.append(f"RSI em {rsi:.0f} — zona neutra, sem sinal claro")

    # =========================================================================
    # 3. MOMENTUM MACD (até 2 pontos) - Direcional puro
    # =========================================================================
    macd = ultimo["macd"]
    macd_sinal = ultimo["macd_sinal"]
    macd_hist = ultimo["macd_hist"]
    macd_hist_ant = penultimo["macd_hist"]
    macd_hist_antes = antes_penultimo["macd_hist"]
    
    # Cruzamento recente?
    cruzou_compra = (penultimo["macd"] <= penultimo["macd_sinal"] 
                     and macd > macd_sinal)
    cruzou_venda = (penultimo["macd"] >= penultimo["macd_sinal"] 
                    and macd < macd_sinal)
    
    # Histograma acelerando?
    hist_acelerando_compra = macd_hist > macd_hist_ant > macd_hist_antes
    hist_acelerando_venda = macd_hist < macd_hist_ant < macd_hist_antes
    
    atr_atual = ultimo["atr"] if pd.notna(ultimo["atr"]) else 0
    zona_morta = 0.03 * atr_atual if atr_atual > 0 else 0.001

    diff_macd = macd - macd_sinal

    if cruzou_compra:
        pontos_compra += 2.0
        motivos_compra.append("MACD CRUZOU pra cima da linha de sinal (mudança de momentum)")
    elif cruzou_venda:
        pontos_venda += 2.0
        motivos_venda.append("MACD CRUZOU pra baixo da linha de sinal (mudança de momentum)")
    elif diff_macd > zona_morta:
        if hist_acelerando_compra:
            pontos_compra += 1.5
            motivos_compra.append("MACD acima do sinal e histograma ACELERANDO pra cima")
        else:
            pontos_compra += 0.5
            motivos_compra.append("MACD acima da linha de sinal (momentum comprador, mas sem aceleração)")
    elif diff_macd < -zona_morta:
        if hist_acelerando_venda:
            pontos_venda += 1.5
            motivos_venda.append("MACD abaixo do sinal e histograma ACELERANDO pra baixo")
        else:
            pontos_venda += 0.5
            motivos_venda.append("MACD abaixo da linha de sinal (momentum vendedor, mas sem aceleração)")

    # =========================================================================
    # 4. ESTOCÁSTICO (até 1.5 pontos) - Confirmação de timing
    # =========================================================================
    stoch_k = ultimo["stoch_k"]
    stoch_d = ultimo["stoch_d"]
    stoch_k_ant = penultimo["stoch_k"]
    
    # Cruzamentos
    stoch_cruzou_compra = stoch_k_ant < stoch_d and stoch_k > stoch_d and stoch_k < 40
    stoch_cruzou_venda = stoch_k_ant > stoch_d and stoch_k < stoch_d and stoch_k > 60
    
    if tendencia_forte_alta or tendencia_muito_forte_alta:
        if stoch_k > 80 and stoch_k > stoch_k_ant:
            pontos_compra += 1.5
            motivos_compra.append(f"Estocástico em {stoch_k:.0f} — momentum forte de alta")
        elif stoch_k < 40 and stoch_k > stoch_k_ant:
            pontos_compra += 1.0
            motivos_compra.append(f"Estocástico em {stoch_k:.0f} — recuo terminando, possível entrada")
        elif stoch_cruzou_compra:
            pontos_compra += 1.0
            motivos_compra.append(f"Estocástico cruzou pra cima em {stoch_k:.0f} — sinal de timing")
    elif tendencia_forte_baixa or tendencia_muito_forte_baixa:
        if stoch_k < 20 and stoch_k < stoch_k_ant:
            pontos_venda += 1.5
            motivos_venda.append(f"Estocástico em {stoch_k:.0f} — momentum forte de baixa")
        elif stoch_k > 60 and stoch_k < stoch_k_ant:
            pontos_venda += 1.0
            motivos_venda.append(f"Estocástico em {stoch_k:.0f} — repique terminando, possível entrada")
        elif stoch_cruzou_venda:
            pontos_venda += 1.0
            motivos_venda.append(f"Estocástico cruzou pra baixo em {stoch_k:.0f} — sinal de timing")
    else:
        if stoch_k < 20 and stoch_k > stoch_k_ant:
            pontos_compra += 1.5
            motivos_compra.append(f"Estocástico em {stoch_k:.0f} — saindo de sobrevenda extrema")
        elif stoch_k > 80 and stoch_k < stoch_k_ant:
            pontos_venda += 1.5
            motivos_venda.append(f"Estocástico em {stoch_k:.0f} — saindo de sobrecompra extrema")
        elif stoch_cruzou_compra:
            pontos_compra += 0.5
            motivos_compra.append(f"Estocástico cruzou pra cima em {stoch_k:.0f}")
        elif stoch_cruzou_venda:
            pontos_venda += 0.5
            motivos_venda.append(f"Estocástico cruzou pra baixo em {stoch_k:.0f}")

    # =========================================================================
    # 5. VOLUME E VWAP (até 1 ponto)
    # =========================================================================
    volume_atual = ultimo["volume"]
    media_volume_20 = df["volume"].rolling(20).mean().iloc[-1]
    vwap = ultimo["vwap"]
    preco = ultimo["close"]
    
    volume_alto = volume_atual > media_volume_20 * 1.3
    volume_muito_alto = volume_atual > media_volume_20 * 2.0
    preco_acima_vwap = preco > vwap
    preco_abaixo_vwap = preco < vwap
    
    if volume_muito_alto and preco_acima_vwap:
        pontos_compra += 1.0
        motivos_compra.append(f"Volume MUITO ALTO ({volume_atual/media_volume_20:.1f}x a média) com preço acima da VWAP")
    elif volume_alto and preco_acima_vwap:
        pontos_compra += 0.5
        motivos_compra.append(f"Volume acima da média com preço acima da VWAP")
    elif volume_muito_alto and preco_abaixo_vwap:
        pontos_venda += 1.0
        motivos_venda.append(f"Volume MUITO ALTO ({volume_atual/media_volume_20:.1f}x a média) com preço abaixo da VWAP")
    elif volume_alto and preco_abaixo_vwap:
        pontos_venda += 0.5
        motivos_venda.append(f"Volume acima da média com preço abaixo da VWAP")

    # =========================================================================
    # 6. SUPORTE/RESISTÊNCIA E ROMPIMENTOS (até 2 pontos BÔNUS)
    # =========================================================================
    resistencia = ultimo["resistencia"]
    suporte = ultimo["suporte"]
    resistencia_ant = penultimo["resistencia"]
    suporte_ant = penultimo["suporte"]
    
    faixa = resistencia - suporte
    if faixa > 0:
        posicao_relativa = (preco - suporte) / faixa
        
        # Rompeu resistência com volume?
        rompeu_resistencia = preco > resistencia_ant and penultimo["close"] <= resistencia_ant
        # Rompeu suporte com volume?
        rompeu_suporte = preco < suporte_ant and penultimo["close"] >= suporte_ant
        
        if rompeu_resistencia:
            if volume_alto:
                pontos_compra += 2.0
                motivos_compra.append(f"ROMPIMENTO DE RESISTÊNCIA EM {resistencia_ant:.2f} COM VOLUME ALTO — sinal forte de continuação")
            else:
                pontos_compra += 1.0
                motivos_compra.append(f"Rompendo resistência em {resistencia_ant:.2f} mas volume fraco — cuidado com falso rompimento")
        elif posicao_relativa > 0.85:
            if tendencia_forte_alta:
                pontos_compra += 0.5
                motivos_compra.append(f"Preço perto da máxima recente, sustentando dentro da tendência")
        
        if rompeu_suporte:
            if volume_alto:
                pontos_venda += 2.0
                motivos_venda.append(f"ROMPIMENTO DE SUPORTE EM {suporte_ant:.2f} COM VOLUME ALTO — sinal forte de continuação")
            else:
                pontos_venda += 1.0
                motivos_venda.append(f"Rompendo suporte em {suporte_ant:.2f} mas volume fraco — cuidado com falso rompimento")
        elif posicao_relativa < 0.15:
            if tendencia_forte_baixa:
                pontos_venda += 0.5
                motivos_venda.append(f"Preço perto da mínima recente, sustentando dentro da tendência")

    # =========================================================================
    # 7. BÔNUS DE CONFLUÊNCIA (até 1 ponto extra)
    # =========================================================================
    # Se todos os indicadores apontam na mesma direção, dá um bônus
    if pontos_compra >= 5 and pontos_venda == 0:
        pontos_compra += 1.0
        motivos_compra.append("BÔNUS: Todos os indicadores alinhados na mesma direção (confluência máxima)")
    elif pontos_venda >= 5 and pontos_compra == 0:
        pontos_venda += 1.0
        motivos_venda.append("BÔNUS: Todos os indicadores alinhados na mesma direção (confluência máxima)")

    # =========================================================================
    # DECISÃO FINAL
    # =========================================================================
    # Arredonda para 1 casa decimal
    pontos_compra = round(pontos_compra, 1)
    pontos_venda = round(pontos_venda, 1)
    
    if abs(pontos_compra - pontos_venda) < 0.5:
        direcao = "neutro"
        score = max(pontos_compra, pontos_venda)
        motivos = (motivos_compra + motivos_venda) or ["Sem sinal claro no momento"]
    elif pontos_compra > pontos_venda:
        direcao = "compra"
        score = pontos_compra
        motivos = motivos_compra
    else:
        direcao = "venda"
        score = pontos_venda
        motivos = motivos_venda

    # Garante que o score nunca seja zero se houver algum motivo
    if score == 0 and motivos:
        score = 0.5

    return {
        "direcao": direcao,
        "score": min(score, 10),  # Cap em 10
        "motivos": motivos,
        "pontos_compra_detalhados": pontos_compra,
        "pontos_venda_detalhados": pontos_venda,
        "preco_atual": float(ultimo["close"]),
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
