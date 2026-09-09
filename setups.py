"""Setups deterministas sobre OHLCV diarios JA FECHADOS, sem I/O.

O chamador deve remover candles parciais: OHLCV sozinho nao comprova fechamento.
Janelas, tick de 0.01, 2R e limites sao hipoteses, nao evidencia de rentabilidade.
Custos, liquidez, aluguel e execucao nao sao modelados.
"""

from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from math import isfinite
from numbers import Real

import numpy as np
import pandas as pd


def _numero(valor):
    return isinstance(valor, Real) and not isinstance(valor, (bool, np.bool_)) and isfinite(valor)


def _data(valor):
    """Data civil BRT; nao consulta relogio nem calendario de negociacao."""
    if not isinstance(valor, (str, date, datetime, pd.Timestamp)):
        raise ValueError("Data invalida")
    if isinstance(valor, str):
        # ISO explicito evita atalhos como 'today'/'now', dependentes do relogio.
        valor = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    data = pd.Timestamp(valor)
    if pd.isna(data):
        raise ValueError("Data invalida")
    if data.tzinfo is not None:
        data = data.tz_convert("America/Sao_Paulo")
    return data.date()


def classificar_setup(df, direcao, risco_retorno_min=2.0, distancia_max_atr=0.5):
    """Retorna plano novo, sem mutar df e sem inferir disparo pelo ultimo OHLC.

    Entrada: DataFrame com open/high/low/close/volume numericos e DatetimeIndex
    crescente, unico, diario. Exige 60 barras anteriores mais a barra de sinal.
    Compra: close > SMA21 > SMA50; venda e o espelho exato.
    Rompimento: close cruza o extremo movel das 20 barras ANTERIORES (tambem
    compara o penultimo close com seu proprio extremo anterior), volume >=
    media das 20 anteriores. Tem prioridade sobre recuo.
    Recuo: range toca SMA21 em algum dos ultimos 5 candles; desde o primeiro
    toque da janela nenhum pavio viola SMA50. Retomada fecha alem do extremo
    do penultimo. Stop no extremo desde esse toque, incluindo o ultimo candle.
    Barreira: maxima/minima anterior mais proxima a partir do gatilho nas 60
    barras anteriores, sem exigir pivo. Barreira no gatilho cancela (espaco zero).
    Sem barreira, projeta exatamente 2R teoricos, mesmo se RR minimo for maior.

    candidato = padrao e plano validos, ainda pendente de cotacao posterior;
    aguardar = historico insuficiente ou padrao ausente; cancelado = invalido.
    Os dois parametros extras no dict preservam a politica para validar_gatilho.
    """
    plano = dict(setup=None, estado="cancelado", motivo="", direcao=direcao,
                 data_sinal=None, gatilho=None, stop=None, alvo=None,
                 risco_retorno=None, alvo_teorico=False,
                 risco_retorno_min=risco_retorno_min, distancia_max_atr=distancia_max_atr)
    if not isinstance(direcao, str) or direcao not in ("compra", "venda"):
        plano["motivo"] = "Direcao deve ser compra ou venda"
        return plano
    if (not _numero(risco_retorno_min) or risco_retorno_min <= 0
            or not _numero(distancia_max_atr) or distancia_max_atr < 0):
        plano["motivo"] = "Parametros de risco invalidos"
        return plano
    colunas = ["open", "high", "low", "close", "volume"]
    if (not isinstance(df, pd.DataFrame) or not df.columns.is_unique
            or not set(colunas).issubset(df.columns)):
        plano["motivo"] = "OHLCV ausente ou colunas invalidas"
        return plano
    if (not isinstance(df.index, pd.DatetimeIndex) or df.index.hasnans
            or not df.index.is_unique or not df.index.is_monotonic_increasing):
        plano["motivo"] = "Indice de datas invalido, duplicado ou fora de ordem"
        return plano
    datas = df.index
    if datas.tz is not None:
        datas = datas.tz_convert("America/Sao_Paulo")
    if not datas.normalize().is_unique:
        plano["motivo"] = "Esperado apenas um candle fechado por dia"
        return plano
    if len(df):
        plano["data_sinal"] = _data(df.index[-1]).isoformat()
    if any(not pd.api.types.is_numeric_dtype(df[c])
           or pd.api.types.is_bool_dtype(df[c])
           or pd.api.types.is_complex_dtype(df[c]) for c in colunas):
        plano["motivo"] = "OHLCV deve ser numerico real"
        return plano
    dados = df[colunas].astype(float)
    if (not np.isfinite(dados.to_numpy()).all()
            or (dados[colunas[:4]] <= 0).any().any() or (dados.volume < 0).any()
            or (dados.low > dados[["open", "close"]].min(axis=1)).any()
            or (dados.high < dados[["open", "close"]].max(axis=1)).any()):
        plano["motivo"] = "OHLCV nao finito, negativo ou geometricamente invalido"
        return plano
    if len(dados) < 61:
        plano.update(estado="aguardar", motivo="Necessarios 61 candles diarios fechados")
        return plano

    sma21 = dados.close.rolling(21).mean()
    sma50 = dados.close.rolling(50).mean()
    ultimo, penultimo = dados.iloc[-1], dados.iloc[-2]
    sinal = 1 if direcao == "compra" else -1
    if not (sinal * (ultimo.close - sma21.iloc[-1]) > 0
            and sinal * (sma21.iloc[-1] - sma50.iloc[-1]) > 0):
        plano.update(estado="aguardar", motivo="Tendencia SMA21/SMA50 nao alinhada")
        return plano
    extremo = dados.high if sinal == 1 else dados.low
    limite = (extremo.rolling(20).max() if sinal == 1
              else extremo.rolling(20).min()).shift(1)
    volume_anterior = dados.volume.iloc[-21:-1].mean()
    rompeu = (sinal * (ultimo.close - limite.iloc[-1]) > 0
              and sinal * (penultimo.close - limite.iloc[-2]) <= 0
              and ultimo.volume >= volume_anterior)
    if rompeu:
        plano["setup"] = "rompimento"
        stop = ultimo.low if sinal == 1 else ultimo.high
    else:
        toques = ((dados.low <= sma21) & (dados.high >= sma21)).iloc[-5:]
        if not toques.any():
            plano.update(estado="aguardar", motivo="Sem rompimento confirmado ou toque na SMA21")
            return plano
        inicio = len(dados) - 5 + int(np.flatnonzero(toques.to_numpy())[0])
        recuo = dados.iloc[inicio:]
        preservou = ((recuo.low >= sma50.iloc[inicio:]).all() if sinal == 1
                     else (recuo.high <= sma50.iloc[inicio:]).all())
        retomou = sinal * (ultimo.close - extremo.iloc[-2]) > 0
        if not preservou or not retomou:
            plano.update(estado="aguardar", motivo="Recuo viola SMA50 ou ainda sem retomada")
            return plano
        plano["setup"] = "recuo"
        stop = recuo.low.min() if sinal == 1 else recuo.high.max()

    # Decimal conserva tick e 2R sem arredondar stops estruturais de OHLC ajustado.
    extremo_sinal = Decimal(str(ultimo.high if sinal == 1 else ultimo.low))
    gatilho = extremo_sinal.quantize(
        Decimal("0.01"), rounding=ROUND_FLOOR if sinal == 1 else ROUND_CEILING,
    ) + sinal * Decimal("0.01")
    stop = Decimal(str(stop))
    risco = sinal * (gatilho - stop)
    plano.update(gatilho=float(gatilho), stop=float(stop))
    if gatilho <= 0 or stop <= 0 or risco <= 0:
        plano["motivo"] = "Entrada, stop ou risco invalidos"
        return plano
    anteriores = extremo.iloc[-61:-1]
    barreiras = anteriores[sinal * (anteriores - float(gatilho)) >= 0]
    teorico = barreiras.empty
    alvo = (gatilho + sinal * 2 * risco if teorico else
            Decimal(str(barreiras.min() if sinal == 1 else barreiras.max())))
    retorno = sinal * (alvo - gatilho)
    rr = retorno / risco
    plano.update(alvo=float(alvo), risco_retorno=float(rr), alvo_teorico=teorico)
    if (alvo <= 0 or retorno <= 0
            or not all(_numero(plano[c]) for c in ("gatilho", "stop", "alvo", "risco_retorno"))):
        plano["motivo"] = "Alvo ou ordem dos precos invalida; sem espaco ate barreira"
    elif rr < Decimal(str(risco_retorno_min)):
        plano["motivo"] = ("Projecao teorica 2R abaixo do RR minimo" if teorico
                           else "Espaco ate barreira abaixo do RR minimo")
    else:
        plano.update(estado="candidato", motivo=(
            "Plano candidato; aguardar cotacao posterior ao sinal. "
            + ("Alvo teorico: projecao 2R, sem barreira nas 60 anteriores."
               if teorico else "Alvo na barreira mais proxima das 60 anteriores.")))
    return plano


def reutilizar_candidato(plano, df, direcao, data_atual):
    """Reusa plano intacto, sem exigir padrao novo nem inferir cruzamento.

    Exige candle do sinal e cobertura dos dias de semana ate ontem. Sem um
    calendario B3, feriado sem candle tambem impede reuso (conservador).
    OHLCV deve estar fechado, como em classificar_setup.
    """
    if (not isinstance(plano, dict) or plano.get("estado") != "candidato"
            or plano.get("direcao") != direcao):
        return None
    # Valida estrutura/risco do plano no gatilho, NAO uma cotacao observada.
    if validar_gatilho(plano, plano.get("gatilho"), 1, data_atual)["estado"] != "candidato":
        return None
    colunas = ["open", "high", "low", "close", "volume"]
    if (not isinstance(df, pd.DataFrame) or not df.columns.is_unique
            or not set(colunas).issubset(df.columns)
            or not isinstance(df.index, pd.DatetimeIndex) or df.index.hasnans
            or not df.index.is_unique or not df.index.is_monotonic_increasing):
        return None
    datas = df.index
    if datas.tz is not None:
        datas = datas.tz_convert("America/Sao_Paulo")
    datas = pd.Index(datas.date)
    hoje, sinal = _data(data_atual), _data(plano["data_sinal"])
    if not datas.is_unique or sinal not in datas or (datas > hoje).any():
        return None
    esperadas = pd.bdate_range(sinal, pd.Timestamp(hoje) - pd.Timedelta(days=1)).date
    if not set(esperadas).issubset(set(datas)):
        return None
    posteriores = df.loc[datas > sinal, colunas]
    if any(not pd.api.types.is_numeric_dtype(posteriores[c])
           or pd.api.types.is_bool_dtype(posteriores[c])
           or pd.api.types.is_complex_dtype(posteriores[c]) for c in colunas):
        return None
    dados = posteriores.astype(float)
    if (not np.isfinite(dados.to_numpy()).all()
            or (dados[colunas[:4]] <= 0).any().any() or (dados.volume < 0).any()
            or (dados.low > dados[["open", "close"]].min(axis=1)).any()
            or (dados.high < dados[["open", "close"]].max(axis=1)).any()):
        return None
    inferior, superior = sorted((plano["stop"], plano["alvo"]))
    if (dados.low <= inferior).any() or (dados.high >= superior).any():
        return None
    return dict(plano)


def validar_gatilho(plano, preco_atual, atr, data_pregao):
    """Retorna copia do plano; candidato significa cotacao elegivel, NAO ordem.

    Aceita somente data civil BRT 1..4 dias APOS data_sinal: aproximacao por dias
    corridos, nao calendario B3 (nao verifica feriados/fins de semana). Mesmo dia
    e rejeitado pois o sinal usa candle diario fechado. Nao usa relogio global.
    Gap e a distancia da cotacao alem do gatilho, nao o gap de abertura.
    preco_atual/ATR devem vir do chamador; nao comprova cruzamento intradiario,
    nem se stop/alvo foram tocados antes. Antes de aceitar candidato, recalcula
    RR no preco informado, mantendo stop/alvo, e exige RR >= risco_retorno_min.
    O campo risco_retorno retornado permanece o planejado no gatilho; a checagem
    na cotacao nao e estimativa de fill nem RR executado.
    """
    resultado = dict(setup=None, estado="cancelado", motivo="Plano invalido",
                     direcao=None, data_sinal=None, gatilho=None, stop=None,
                     alvo=None, risco_retorno=None, alvo_teorico=False)
    if not isinstance(plano, dict):
        return resultado
    resultado.update(plano)
    resultado.update(estado="cancelado", motivo="Plano invalido")
    if (not all(isinstance(plano.get(c), str) for c in ("setup", "direcao", "estado"))
            or plano["setup"] not in ("rompimento", "recuo")
            or plano["direcao"] not in ("compra", "venda")
            or plano["estado"] not in ("candidato", "aguardar")):
        return resultado
    campos = ("gatilho", "stop", "alvo", "risco_retorno", "risco_retorno_min", "distancia_max_atr")
    if (not all(_numero(plano.get(c)) for c in campos)
            or not _numero(preco_atual) or preco_atual <= 0
            or not _numero(atr) or atr <= 0
            or plano["risco_retorno_min"] <= 0 or plano["distancia_max_atr"] < 0
            or not isinstance(plano.get("alvo_teorico"), bool)):
        resultado["motivo"] = "Plano, preco, ATR ou parametros invalidos"
        return resultado
    sinal = 1 if plano["direcao"] == "compra" else -1
    gatilho, stop, alvo, preco, atr_d = map(Decimal, map(str, (
        plano["gatilho"], plano["stop"], plano["alvo"], preco_atual, atr)))
    risco, retorno = sinal * (gatilho - stop), sinal * (alvo - gatilho)
    if (min(gatilho, stop, alvo) <= 0 or risco <= 0 or retorno <= 0
            or retorno / risco < Decimal(str(plano["risco_retorno_min"]))
            or not np.isclose(float(retorno / risco), plano["risco_retorno"], rtol=1e-12, atol=0)):
        resultado["motivo"] = "Ordem de entrada/stop/alvo ou risco-retorno invalido"
        return resultado
    try:
        idade = (_data(data_pregao) - _data(plano.get("data_sinal"))).days
    except (ValueError, TypeError, OverflowError):
        resultado["motivo"] = "Data de pregao ou sinal invalida"
        return resultado
    if not 1 <= idade <= 4:
        resultado["motivo"] = "Data deve ser posterior ao sinal e ate 4 dias corridos (aproximacao de calendario)"
    elif sinal * (preco - stop) <= 0:
        resultado["motivo"] = "Stop invalidado pela cotacao"
    elif sinal * (preco - alvo) >= 0:
        resultado["motivo"] = "Alvo atingido ou ultrapassado pela cotacao"
    elif sinal * (preco - gatilho) < 0:
        resultado.update(estado="aguardar", motivo="Cotacao ainda nao alcancou o gatilho na direcao do plano")
    elif sinal * (preco - gatilho) > Decimal(str(plano["distancia_max_atr"])) * atr_d:
        resultado["motivo"] = "Gap alem do gatilho excede distancia maxima em ATR"
    elif sinal * (alvo - preco) / (sinal * (preco - stop)) < Decimal(str(plano["risco_retorno_min"])):
        resultado["motivo"] = "Risco-retorno no preco informado abaixo do minimo; nao perseguir o preco"
    else:
        resultado.update(estado="candidato", motivo="Cotacao elegivel na direcao do gatilho; nao comprova execucao")
    return resultado
