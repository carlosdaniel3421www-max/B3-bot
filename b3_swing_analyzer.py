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

def baixar_dados(ticker: str, periodo: str = "1y", intervalo: str = "1d") -> pd.DataFrame:
    """Baixa dados históricos via yfinance. Ticker sem sufixo -> adiciona .SA (B3)."""
    import yfinance as yf

    if not ticker.upper().endswith(".SA"):
        ticker = ticker.upper() + ".SA"

    df = yf.download(ticker, period=periodo, interval=intervalo, auto_adjust=True, progress=False)

    if df.empty:
        raise ValueError(f"Não foi possível baixar dados para {ticker}. Verifique o código do ativo.")

    # yfinance às vezes retorna colunas MultiIndex quando baixa 1 ticker só
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns=str.lower)
    df.index.name = "date"
    return df


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


def sugerir_stop_alvo(df: pd.DataFrame, direcao: str) -> dict:
    """
    Sugere stop-loss e alvo (take-profit) com base em ATR e suporte/resistência.
    direcao: "compra" ou "venda"
    Regra: stop = 1.5x ATR além do suporte/resistência; alvo = risco:retorno de 2:1.
    """
    ultimo = df.iloc[-1]
    preco = ultimo["close"]
    atr = ultimo["atr"]

    if direcao == "compra":
        stop = min(ultimo["suporte"], preco - 1.5 * atr)
        risco = preco - stop
        alvo = preco + 2 * risco
    else:  # venda
        stop = max(ultimo["resistencia"], preco + 1.5 * atr)
        risco = stop - preco
        alvo = preco - 2 * risco

    return {
        "preco_entrada": round(preco, 2),
        "stop": round(stop, 2),
        "alvo": round(alvo, 2),
        "risco_por_acao": round(abs(risco), 2),
        "relacao_risco_retorno": "1:2",
    }


# --------------------------------------------------------------------------
# 3. PLACAR DE CONFLUÊNCIA (heurística simples, não é garantia de nada)
# --------------------------------------------------------------------------

def gerar_placar(df: pd.DataFrame) -> dict:
    ultimo = df.iloc[-1]
    pontos = 0
    motivos = []

    # Tendência
    if ultimo["close"] > ultimo["sma21"] > ultimo["sma50"]:
        pontos += 1
        motivos.append("Preço acima da SMA21 e SMA21 acima da SMA50 (tendência de alta)")
    elif ultimo["close"] < ultimo["sma21"] < ultimo["sma50"]:
        pontos -= 1
        motivos.append("Preço abaixo da SMA21 e SMA21 abaixo da SMA50 (tendência de baixa)")

    # RSI
    if ultimo["rsi"] < 30:
        pontos += 1
        motivos.append(f"RSI em {ultimo['rsi']:.1f} (zona de sobrevenda)")
    elif ultimo["rsi"] > 70:
        pontos -= 1
        motivos.append(f"RSI em {ultimo['rsi']:.1f} (zona de sobrecompra)")

    # MACD
    if ultimo["macd"] > ultimo["macd_sinal"] and ultimo["macd_hist"] > 0:
        pontos += 1
        motivos.append("MACD acima da linha de sinal (momentum positivo)")
    elif ultimo["macd"] < ultimo["macd_sinal"] and ultimo["macd_hist"] < 0:
        pontos -= 1
        motivos.append("MACD abaixo da linha de sinal (momentum negativo)")

    # Estocástico
    if ultimo["stoch_k"] < 20:
        pontos += 1
        motivos.append(f"Estocástico em {ultimo['stoch_k']:.1f} (sobrevenda)")
    elif ultimo["stoch_k"] > 80:
        pontos -= 1
        motivos.append(f"Estocástico em {ultimo['stoch_k']:.1f} (sobrecompra)")

    # Proximidade de suporte/resistência
    faixa = ultimo["resistencia"] - ultimo["suporte"]
    if faixa > 0:
        dist_suporte = (ultimo["close"] - ultimo["suporte"]) / faixa
        if dist_suporte < 0.1:
            pontos += 1
            motivos.append("Preço próximo do suporte recente")
        elif dist_suporte > 0.9:
            pontos -= 1
            motivos.append("Preço próximo da resistência recente")

    # Volume vs VWAP
    if ultimo["close"] > ultimo["vwap"]:
        motivos.append("Preço acima da VWAP móvel (força compradora)")
    else:
        motivos.append("Preço abaixo da VWAP móvel (força vendedora)")

    if pontos >= 2:
        classificacao = "POSSÍVEL ENTRADA DE COMPRA"
    elif pontos <= -2:
        classificacao = "POSSÍVEL ENTRADA DE VENDA"
    else:
        classificacao = "SEM CONFLUÊNCIA CLARA (aguardar)"

    return {
        "pontos": pontos,
        "classificacao": classificacao,
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

    placar = gerar_placar(df)

    print("\n" + "=" * 60)
    print(f"ATIVO: {args.ticker.upper()}  |  DATA: {placar['data'].date()}")
    print(f"PREÇO ATUAL: R$ {placar['preco_atual']:.2f}")
    print(f"PLACAR DE CONFLUÊNCIA: {placar['pontos']:+d}")
    print(f"CLASSIFICAÇÃO: {placar['classificacao']}")
    print("-" * 60)
    print("Motivos considerados:")
    for m in placar["motivos"]:
        print(f"  • {m}")
    print("=" * 60)
    print("\nAVISO: Ferramenta de apoio técnico, não é recomendação de")
    print("investimento. Sempre valide com sua própria análise de risco.\n")

    caminho_saida = args.saida or f"{args.ticker.upper()}_analise.png"
    plotar_grafico(df, args.ticker.upper(), caminho_saida)
    print(f"Gráfico salvo em: {caminho_saida}")


if __name__ == "__main__":
    main()
