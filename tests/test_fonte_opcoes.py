# -*- coding: utf-8 -*-
"""Testes do módulo fonte_opcoes (API opcoes.net.br) com mock, sem rede."""
from unittest.mock import patch, MagicMock
import pytest
from fonte_opcoes import (
    buscar_cadeia_opcoesnet,
    buscar_cadeia_estruturada,
    buscar_melhor_vencimento,
    buscar_premio_real,
    limpar_cache_cadeia,
)


@pytest.fixture(autouse=True)
def _limpa_cache():
    """Limpa o cache entre testes para não vazar dados de um mock pro outro."""
    limpar_cache_cadeia()
    yield
    limpar_cache_cadeia()


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
                                ["J186", 0, "A", 9.86, "I", -0.0179, 0.24, 0.0, None, 10, 5000, 0.0, 0, 0, 0, 0, 0, 35.2, 0.55, 0.0, 0.0, 0.0, 0.0],
                                ["J196", 0, "A", 10.06, "A", 0.0019, 0.61, 0.0, None, 12, 6495, 0.0, 0, 0, 0, 0, 0, 33.8, 0.52, 0.0, 0.0, 0.0, 0.0],
                                ["J218", 0, "A", 10.86, "O", 0.081, 0.22, 0.0, None, 10, 5222, 0.0, 0, 0, 0, 0, 0, 36.5, 0.42, 0.0, 0.0, 0.0, 0.0],
                                ["J231", 0, "A", 11.56, "O", 0.151, 0.09, 0.0, None, 10, 2698, 0.0, 0, 0, 0, 0, 0, 38.1, 0.35, 0.0, 0.0, 0.0, 0.0],
                            ],
                            "puts": [
                                ["J086", 0, "A", 9.06, "O", -0.097, 0.07, 0.0, None, 5, 1000, 0.0, 0, 0, 0, 0, 0, 34.0, -0.45, 0.0, 0.0, 0.0, 0.0],
                                ["J096", 0, "A", 9.86, "O", -0.017, 0.24, 0.0, None, 8, 2000, 0.0, 0, 0, 0, 0, 0, 32.5, -0.40, 0.0, 0.0, 0.0, 0.0],
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


def test_vol_impl_mediana_calls():
    from fonte_opcoes import vol_impl_mediana, limpar_cache_cadeia
    limpar_cache_cadeia()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        cadeia = buscar_cadeia_estruturada("CMIG4")
    vi = vol_impl_mediana(cadeia, tipo="call")
    assert vi is not None
    assert 32.0 < vi < 40.0  # vol_impl entre 32% e 38%


def test_vol_impl_mediana_ambos():
    from fonte_opcoes import vol_impl_mediana, limpar_cache_cadeia
    limpar_cache_cadeia()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        cadeia = buscar_cadeia_estruturada("CMIG4")
    vi = vol_impl_mediana(cadeia)
    assert vi is not None


def test_vol_impl_mediana_cadeia_vazia():
    from fonte_opcoes import vol_impl_mediana
    assert vol_impl_mediana(None) is None


def test_cache_cadeia_funciona():
    from fonte_opcoes import limpar_cache_cadeia
    limpar_cache_cadeia()
    # Primeira chamada: busca na API
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp) as mock_get:
        c1 = buscar_cadeia_opcoesnet("CMIG4")
        assert c1 is not None
        assert mock_get.call_count == 1
    # Segunda chamada: deve usar cache (não chamar a API)
    with patch("fonte_opcoes.requests.get") as mock_get2:
        c2 = buscar_cadeia_opcoesnet("CMIG4")
        assert c2 is not None
        assert mock_get2.call_count == 0  # não chamou a API


def test_buscar_cadeia_estruturada_vol_impl():
    from fonte_opcoes import limpar_cache_cadeia
    limpar_cache_cadeia()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = _mock_payload()
    with patch("fonte_opcoes.requests.get", return_value=mock_resp):
        cadeia = buscar_cadeia_estruturada("CMIG4")
    assert cadeia is not None
    venc = cadeia["expirations"][0]
    # Verificar vol_impl e delta extraídos
    call_1086 = venc["calls"][10.86]
    assert call_1086["vol_impl"] == 36.5
    assert call_1086["delta"] == 0.42
