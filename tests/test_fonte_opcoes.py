# -*- coding: utf-8 -*-
"""Testes do módulo fonte_opcoes (API opcoes.net.br) com mock, sem rede."""
from unittest.mock import patch, MagicMock
from fonte_opcoes import (
    buscar_cadeia_opcoesnet,
    buscar_cadeia_estruturada,
    buscar_melhor_vencimento,
    buscar_premio_real,
)


def _mock_payload():
    """Payload simulado da API do opcoes.net.br."""
    return {
        "success": True,
        "requests": [
            {"type": "LastQuotesInfo", "results": {"dateLastQuotesInDB": "2026-08-21"}},
            {
                "type": "OptionsChain",
                "results": {
                    "underlying_asset": {"symbol": "CMIG4", "p": 10.04},
                    "strikes": {"list": [9.06, 9.86, 10.06, 10.86, 11.06, 11.56]},
                    "expirations": [
                        {
                            "dt": "2026-09-18", "du": 18, "m": True,
                            "calls": [
                                ["J186", 0, "A", 9.86, "I", -0.0179, 0.24, 0.0, None, 10, 5000, 0.3],
                                ["J196", 0, "A", 10.06, "A", 0.0019, 0.61, 0.0, None, 12, 6495, 0.3],
                                ["J218", 0, "A", 10.86, "O", 0.081, 0.22, 0.0, None, 10, 5222, 0.3],
                                ["J231", 0, "A", 11.56, "O", 0.151, 0.09, 0.0, None, 10, 2698, 0.3],
                            ],
                            "puts": [
                                ["J086", 0, "A", 9.06, "O", -0.097, 0.07, 0.0, None, 5, 1000, 0.3],
                                ["J096", 0, "A", 9.86, "O", -0.017, 0.24, 0.0, None, 8, 2000, 0.3],
                            ],
                        },
                    ],
                },
            },
        ],
    }


def test_buscar_cadeia_opcoesnet_sucesso():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        cadeia = buscar_cadeia_opcoesnet("CMIG4")
    assert cadeia is not None
    assert cadeia["ticker"] == "CMIG4"
    assert cadeia["preco_base"] == 10.04
    assert len(cadeia["expirations"]) == 1
    assert len(cadeia["expirations"][0]["calls"]) == 4


def test_buscar_cadeia_opcoesnet_falha_rede():
    with patch("fonte_opcoes.requests.get", side_effect=Exception("timeout")):
        cadeia = buscar_cadeia_opcoesnet("CMIG4")
    assert cadeia is None


def test_buscar_cadeia_opcoesnet_status_erro():
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        cadeia = buscar_cadeia_opcoesnet("CMIG4")
    assert cadeia is None


def test_buscar_cadeia_estruturada():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        cadeia = buscar_cadeia_estruturada("CMIG4")
    assert cadeia is not None
    assert cadeia["preco_base"] == 10.04
    venc = cadeia["expirations"][0]
    assert 10.86 in venc["calls"]
    assert venc["calls"][10.86]["preco"] == 0.22
    assert venc["calls"][10.86]["negocios"] == 10


def test_buscar_melhor_vencimento_prefere_mensal():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        cadeia = buscar_cadeia_estruturada("CMIG4")
    venc = buscar_melhor_vencimento(cadeia)
    assert venc is not None
    assert venc["mensal"] is True
    assert venc["dt"] == "2026-09-18"


def test_buscar_premio_real():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        r = buscar_premio_real("CMIG4", 10.5, "call")
    assert r is not None
    assert r["strike_real"] == 10.86
    assert r["premio"] == 0.22
    assert r["vencimento"] == "2026-09-18"


def test_buscar_premio_real_put():
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        r = buscar_premio_real("CMIG4", 9.8, "put")
    assert r is not None
    assert r["strike_real"] == 9.86
    assert r["premio"] == 0.24


def test_buscar_premio_real_cadeia_falha():
    with patch("fonte_opcoes.requests.get", side_effect=Exception("offline")):
        r = buscar_premio_real("CMIG4", 10.5, "call")
    assert r is None
