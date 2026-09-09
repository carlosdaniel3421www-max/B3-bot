"""Regressao de integracao: relatorio nao contorna politica de vencimento."""
from unittest.mock import Mock

import relatorio_diario as rd


def test_legado_nao_substitui_serie_inelegivel_por_estimativa(monkeypatch):
    monkeypatch.setattr(rd.config, "EXIGIR_SETUP", False)
    monkeypatch.setattr(rd, "_montar_analisador_ia", Mock(return_value=None))
    monkeypatch.setattr("fonte_opcoes.buscar_cadeia_estruturada", Mock(return_value=None))
    montar = Mock(side_effect=ValueError("Sem serie elegivel"))
    monkeypatch.setattr("trava.montar_trava", montar)
    formatar = Mock()
    monkeypatch.setattr("trava.formatar_trava", formatar)
    resposta = rd.rodar_analise_trava_ia([
        {"ticker": "CMIG4", "score": 8, "direcao": "compra", "preco": 10},
    ])
    assert montar.call_args.kwargs["permitir_estimativa"] is False
    assert "14 e 30 dias corridos" in resposta
    assert "Nao substituir" in resposta
    formatar.assert_not_called()
