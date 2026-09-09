"""Execucao OHLC com dados sinteticos, sem rede."""
import pandas as pd
import pytest

import backtest


@pytest.fixture
def simular(monkeypatch):
    def executar(barras, direcao="compra", max_dias=20):
        base = [{"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0}] * 211
        df = pd.DataFrame(base + barras, index=pd.bdate_range("2025-01-01", periods=211 + len(barras)))
        monkeypatch.setattr(backtest, "baixar_dados", lambda *args, **kwargs: df.copy())
        monkeypatch.setattr(backtest, "calcular_indicadores", lambda dados: dados)
        chamadas = []
        def avaliar(dados):
            chamadas.append(dados.index[-1])
            return {"score": 9 if len(dados) == 211 else 0, "direcao": direcao}
        def limites(dados, sentido):
            assert dados.index[-1] == df.index[210]
            return {"stop": 95.0 if sentido == "compra" else 105.0,
                    "alvo": 110.0 if sentido == "compra" else 90.0}
        monkeypatch.setattr(backtest, "avaliar_ativo", avaliar)
        monkeypatch.setattr(backtest, "sugerir_stop_alvo", limites)
        resultado = backtest.rodar_backtest("PETR4", max_dias_holding=max_dias)
        return resultado, df, chamadas
    return executar


@pytest.mark.parametrize("direcao,high,low,motivo,saida", [
    ("compra", 102, 94, "stop", 95),
    ("venda", 106, 98, "stop", 105),
    ("compra", 112, 98, "alvo", 110),
    ("venda", 102, 88, "alvo", 90),
    ("compra", 112, 94, "stop", 95),
    ("venda", 106, 88, "stop", 105),
])
def test_saida_no_dia_entrada_inclusive_ultima_barra(simular, direcao, high, low, motivo, saida):
    resultado, df, chamadas = simular([
        {"open": 100, "high": high, "low": low, "close": 100},
    ], direcao)
    trade, = resultado["trades"]
    assert trade["data_entrada"] == trade["data_saida"] == df.index[-1]
    assert trade["dias_no_trade"] == 0
    assert trade["motivo_saida"] == motivo
    assert trade["preco_saida"] == saida
    assert chamadas == [df.index[210]]  # sinal nao ve a barra de entrada


@pytest.mark.parametrize("direcao,abertura,high,low,saida,motivo", [
    ("compra", 90, 112, 88, 90, "stop"),
    ("venda", 112, 114, 88, 112, "stop"),
    ("compra", 115, 117, 90, 110, "alvo"),
    ("venda", 85, 110, 83, 90, "alvo"),
])
def test_gap_posicao_aberta_respeita_abertura_e_limite_conservador(
        simular, direcao, abertura, high, low, saida, motivo):
    resultado, df, chamadas = simular([
        {"open": 100, "high": 102, "low": 98, "close": 101},
        {"open": abertura, "high": high, "low": low, "close": 100},
    ], direcao)
    trade, = resultado["trades"]
    assert trade["preco_saida"] == saida
    assert trade["motivo_saida"] == motivo
    assert trade["data_saida"] == df.index[-1]
    assert trade["dias_no_trade"] == 1
    assert chamadas == [df.index[210]]  # nao cria outra posicao enquanto aberta


@pytest.mark.parametrize("direcao,abertura", [
    ("compra", 90), ("compra", 95), ("compra", 110), ("compra", 115),
    ("venda", 85), ("venda", 90), ("venda", 105), ("venda", 112),
])
def test_gap_entrada_fora_limites_cancela_sem_lucro_ficticio(simular, direcao, abertura):
    resultado, _, _ = simular([
        {"open": abertura, "high": max(120, abertura), "low": min(80, abertura), "close": 100},
    ], direcao)
    assert resultado["total_trades"] == 0


def test_entrada_na_abertura_nao_fechamento_e_prazo(simular):
    resultado, _, _ = simular([
        {"open": 101, "high": 104, "low": 99, "close": 103},
        {"open": 102, "high": 104, "low": 99, "close": 103},
    ], max_dias=1)
    trade, = resultado["trades"]
    assert trade["preco_entrada"] == 101
    assert trade["preco_saida"] == 103
    assert trade["motivo_saida"] == "prazo_maximo"
    assert trade["retorno_pct"] == (103 - 101) / 101 * 100


def test_stop_tem_prioridade_sobre_prazo(simular):
    resultado, _, _ = simular([
        {"open": 100, "high": 102, "low": 94, "close": 101},
    ], max_dias=0)
    assert resultado["trades"][0]["motivo_saida"] == "stop"


def test_direcao_neutra_nao_abre_venda(simular):
    resultado, _, _ = simular([
        {"open": 100, "high": 120, "low": 80, "close": 100},
    ], direcao="neutro")
    assert resultado["total_trades"] == 0


def test_indicadores_do_sinal_nao_mudam_com_barras_futuras():
    # Verifica tambem a causalidade da implementacao real dos indicadores.
    precos = pd.Series([100 + i * 0.03 + (i % 7) for i in range(230)])
    df = pd.DataFrame({"open": precos, "close": precos + 0.5,
                       "high": precos + 2, "low": precos - 2, "volume": 10000})
    prefixo = backtest.calcular_indicadores(df.iloc[:211].copy())
    df.loc[211:, ["open", "high", "low", "close"]] *= 10
    completo = backtest.calcular_indicadores(df.copy())
    pd.testing.assert_frame_equal(prefixo, completo.iloc[:211])
