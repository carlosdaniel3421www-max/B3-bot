# -*- coding: utf-8 -*-
"""Testes do filtro da IA (score >= 8) e da ordenação do ranking."""
import pandas as pd
from unittest.mock import patch


def _fake_df():
    return pd.DataFrame([{
        "ema21": 10.0, "ema200": 9.0, "rsi": 60.0, "macd": 0.1,
        "volume": 1000.0, "atr": 0.3, "suporte": 9.5, "resistencia": 11.0,
    }])


def _fake_resultado(ticker, score, direcao):
    return {
        "ticker": ticker,
        "score": score,
        "direcao": direcao,
        "preco": 10.0,
        "motivos": ["motivo"],
        "df": _fake_df(),
    }


class AnalisadorFake:
    def __init__(self):
        self.analisados = []
        self.ultimo_provedor = "gemini"

    def analyze_asset(self, **kwargs):
        self.analisados.append(kwargs["ticker"])
        return {"resumo": "ok", "concordar": True, "pros": [], "contras": [],
                "riscos": [], "score_ia": 80}

    def format_telegram_message(self, resultado):
        return "ok"


def test_ia_analisa_apenas_score_8_mais():
    import relatorio_diario as rd
    analisador = AnalisadorFake()
    resultados = [
        _fake_resultado("CMIG4", 8, "venda"),   # analisa (>= 8)
        _fake_resultado("PETR4", 7, "compra"),  # NÃO analisa (< 8)
        _fake_resultado("VALE3", 5, "compra"),  # NÃO analisa
        _fake_resultado("NEUTRO", 9, "neutro"), # NÃO analisa (direção neutra)
    ]
    with patch.object(rd, "_montar_analisador_ia", return_value=analisador):
        with patch.object(rd, "checar_risco_noticias", return_value={"noticias": []}):
            rd.rodar_analise_ia(resultados, "estado.json")
    assert analisador.analisados == ["CMIG4"]


def test_ia_sem_candidatos():
    import relatorio_diario as rd
    analisador = AnalisadorFake()
    resultados = [_fake_resultado("PETR4", 6, "compra")]
    with patch.object(rd, "_montar_analisador_ia", return_value=analisador):
        msg = rd.rodar_analise_ia(resultados, "estado.json")
    assert analisador.analisados == []
    assert "Nenhum ativo" in msg


def test_trava_ia_analisa_apenas_score_8_mais():
    import relatorio_diario as rd
    resultados = [
        _fake_resultado("CMIG4", 8, "venda"),
        _fake_resultado("PETR4", 7, "compra"),
    ]
    chamados = []

    def fake_montar_trava(preco, direcao, cadeia_real=None, ticker=None):
        chamados.append(ticker)
        return {}
    fake_formatar = lambda t, p: "ok"

    with patch.object(rd, "_montar_analisador_ia", return_value=None):
        with patch("trava.montar_trava", side_effect=fake_montar_trava):
            with patch("trava.formatar_trava", side_effect=fake_formatar):
                with patch("fonte_opcoes.buscar_cadeia_estruturada", return_value={}):
                    rd.rodar_analise_trava_ia(resultados)
    assert chamados == ["CMIG4"]


def test_ordenacao_ranking_suavizado_decrescente():
    import relatorio_diario as rd
    # Simula a ordenação que acontece em gerar_e_enviar_relatorio:
    # ordena por score suavizado (o exibido), com tiebreaker pelo bruto.
    resultados = [
        {"ticker": "B", "score": 8, "score_bruto": 9},
        {"ticker": "A", "score": 8, "score_bruto": 8},
        {"ticker": "C", "score": 6, "score_bruto": 10},
        {"ticker": "D", "score": 9, "score_bruto": 5},
    ]
    resultados.sort(key=lambda r: (r["score"], r.get("score_bruto", r["score"])), reverse=True)
    ordem = [r["ticker"] for r in resultados]
    assert ordem == ["D", "B", "A", "C"]
