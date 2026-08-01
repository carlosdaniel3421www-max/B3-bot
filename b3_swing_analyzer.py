import argparse
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates


def baixar_dados(ticker: str, periodo: str = "1y", intervalo: str = "1d", tentativas: int = 3) -> pd.DataFrame:
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
            time.sleep(2 * tentativa)

    raise ValueError(f"Não foi possível baixar dados para {ticker} após {tentativas} tentativas. Último erro: {ultimo_erro}")


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
    preco_tipico = (df["high"] + df["low"] + df["close"]) / 3
    pv = preco_tipico * df["volume"]
    df["vwap"] = pv.rolling(janela).sum() / df["volume"].rolling(janela).sum()
    return df


def calcular_suporte_resistencia(df: pd.DataFrame, janela: int = 20) -> pd.DataFrame:
    df["resistencia"] = df["high"].rolling(janela).max()
    df["suporte"] = df["low"].rolling(janela).min()
    return df


def calcular_atr(df: pd.DataFrame, periodo: int = 14) -> pd.DataFrame:
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
    ultimo = df.iloc[-1]
    preco = ultimo["close"]
    atr = ultimo["atr"]

    if direcao == "compra":
        stop = min(ultimo["suporte"], preco - atr_mult * atr)
        piso_stop = preco - risco_maximo_atr_mult * atr
        stop = max(stop, piso_stop)
        risco = preco - stop
        alvo = preco + risco_retorno * risco
    else:
        stop = max(ultimo["resistencia"], preco + atr_mult * atr)
        teto_stop = preco + risco_maximo_atr_mult * atr
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


def avaliar_ativo(df: pd.DataFrame) -> dict:
    """
    Avaliação calibrada (0 a 10): Exige confluência real para notas altas.
    Ativos sem direção clara ficam com notas baixas (3 a 5).
    """
    ultimo = df.iloc[-1]
    penultimo = df.iloc[-2] if len(df) > 1 else ultimo

    pontos_compra, pontos_venda = 0, 0
    motivos_compra, motivos_venda = [], []

    # --- 1. TENDÊNCIA E ALINHAMENTO (Até 4 pontos) ---
    tendencia_alta = ultimo["sma21"] > ultimo["sma50"] and ultimo["close"] > ultimo["sma21"]
    tendencia_baixa = ultimo["sma21"] < ultimo["sma50"] and ultimo["close"] < ultimo["sma21"]

    if tendencia_alta:
        pontos_compra += 2.5
        motivos_compra.append("Tendência de alta estabelecida (Preço > SMA21 > SMA50)")
        if ultimo["sma9"] > ultimo["sma21"]:
            pontos_compra += 1.5
            motivos_compra.append("Curto prazo alinhado para cima (SMA9 > SMA21)")
    elif tendencia_baixa:
        pontos_venda += 2.5
        motivos_venda.append("Tendência de baixa estabelecida (Preço < SMA21 < SMA50)")
        if ultimo["sma9"] < ultimo["sma21"]:
            pontos_venda += 1.5
            motivos_venda.append("Curto prazo alinhado para baixo (SMA9 < SMA21)")

    # --- 2. MOMENTUM: MACD E RSI (Até 4 pontos) ---
    if ultimo["macd"] > ultimo["macd_sinal"]:
        pontos_compra += 2
        motivos_compra.append("MACD comprador positivo")
    elif ultimo["macd"] < ultimo["macd_sinal"]:
        pontos_venda += 2
        motivos_venda.append("MACD vendedor negativo")

    rsi = ultimo["rsi"]
    if 48 <= rsi <= 65:
        pontos_compra += 2
        motivos_compra.append(f"RSI em {rsi:.0f} (zona ideal de continuação de alta)")
    elif 35 <= rsi <= 52:
        pontos_venda += 2
        motivos_venda.append(f"RSI em {rsi:.0f} (zona ideal de continuação de baixa)")

    # --- 3. VOLUME E CONTEXTO (Até 2 pontos) ---
    media_volume = df["volume"].rolling(20).mean().iloc[-1]
    if ultimo["volume"] > media_volume * 1.2:
        pontos_compra += 1
        pontos_venda += 1
        motivos_compra.append("Volume financeiro forte (> 20% da média)")
        motivos_venda.append("Volume financeiro forte (> 20% da média)")

    faixa = ultimo["resistencia"] - ultimo["suporte"]
    if faixa > 0:
        dist = (ultimo["close"] - ultimo["suporte"]) / faixa
        if dist > 0.85 and tendencia_alta:
            pontos_compra += 1
            motivos_compra.append("Pressionando resistência máxima recente")
        elif dist < 0.15 and tendencia_baixa:
            pontos_venda += 1
            motivos_venda.append("Pressionando suporte mínimo recente")

    score_c = int(round(min(10, pontos_compra)))
    score_v = int(round(min(10, pontos_venda)))

    if score_c == score_v:
        direcao = "neutro"
        score = score_c
        motivos = ["Sem confluência direcional clara no momento"]
    elif score_c > score_v:
        direcao = "compra"
        score = score_c
        motivos = motivos_compra
    else:
        direcao = "venda"
        score = score_v
        motivos = motivos_venda

    return {
        "direcao": direcao,
        "score": score,
        "motivos": motivos or ["Ativo lateralizado ou sem força"],
        "preco_atual": ultimo["close"],
        "data": df.index[-1],
    }


def plotar_grafico(df: pd.DataFrame, ticker: str, caminho_saida: str):
    fig, eixos = plt.subplots(
        4, 1, figsize=(14, 12), sharex=True,
        gridspec_kw={"height_ratios": [3, 1, 1, 1]}
    )
    ax_preco, ax_vol, ax_rsi_stoch, ax_macd = eixos

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

    cores_vol = np.where(df["close"] >= df["close"].shift(1), "green", "red")
    ax_vol.bar(df.index, df["volume"], color=cores_vol, alpha=0.6, width=1)
    ax_vol.set_ylabel("Volume")
    ax_vol.grid(alpha=0.3)

    ax_rsi_stoch.plot(df.index, df["rsi"], label="RSI(14)", color="blue", linewidth=0.9)
    ax_rsi_stoch.plot(df.index, df["stoch_k"], label="%K Estocástico", color="orange", linewidth=0.7)
    ax_rsi_stoch.axhline(70, color="red", linestyle="--", linewidth=0.6)
    ax_rsi_stoch.axhline(30, color="green", linestyle="--", linewidth=0.6)
    ax_rsi_stoch.set_ylabel("RSI / Estocástico")
    ax_rsi_stoch.legend(loc="upper left", fontsize=8)
    ax_rsi_stoch.grid(alpha=0.3)

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

    caminho_saida = args.saida or f"{args.ticker.upper()}_analise.png"
    plotar_grafico(df, args.ticker.upper(), caminho_saida)
    print(f"Gráfico salvo em: {caminho_saida}")


if __name__ == "__main__":
    main()
