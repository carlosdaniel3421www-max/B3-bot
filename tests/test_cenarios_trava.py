"""Testes locais: nenhuma rede, persistencia ou alteracao da trava de entrada."""

from copy import deepcopy
from html import escape
import json

import pytest

from cenarios_trava import analisar_cenarios_trava, formatar_cenarios_trava
from trava import calcular_trava_manual, montar_trava


@pytest.fixture(autouse=True)
def sem_rede(monkeypatch):
    def bloquear(*args, **kwargs):
        pytest.fail("Rede proibida")
    monkeypatch.setattr("socket.socket.connect", bloquear)
    monkeypatch.setattr("socket.create_connection", bloquear)


@pytest.fixture
def alta():
    return calcular_trava_manual("compra", 100, 3, 110, 1, contratos=37)


@pytest.fixture
def baixa():
    return calcular_trava_manual("venda", 100, 3, 90, 1, contratos=37)


@pytest.mark.parametrize("direcao", ["compra", "venda"])
@pytest.mark.parametrize("contratos", [1, 37, 250.0])
def test_integra_montar_trava_sem_mutacao(direcao, contratos):
    trava = montar_trava(30, direcao, contratos=contratos)
    antes = deepcopy(trava)
    analise = analisar_cenarios_trava(trava, 30)
    assert trava == antes
    assert analise == analisar_cenarios_trava(trava, 30)
    assert analise["contratos"] == contratos
    for campo in ("custo_total", "risco_maximo", "ganho_maximo", "breakeven"):
        assert analise[campo] == pytest.approx(trava[campo])
    assert [c["variacao_pct"] for c in analise["cenarios"]] == [-10, -5, 0, 5, 10]
    assert json.loads(json.dumps(analise, allow_nan=False)) == analise


def test_simetria_bull_call_bear_put(alta, baixa):
    bull = analisar_cenarios_trava(alta, 100)
    bear = analisar_cenarios_trava(baixa, 100)
    for call, put in zip(bull["cenarios"], reversed(bear["cenarios"])):
        assert call["pnl_total"] == pytest.approx(put["pnl_total"])
    assert bull["breakeven"] == 102
    assert bear["breakeven"] == 98
    assert bull["risco_maximo"] == bear["risco_maximo"] == 74
    assert bull["ganho_maximo"] == bear["ganho_maximo"] == 296


@pytest.mark.parametrize("direcao,kv", [("compra", 110), ("venda", 90)])
@pytest.mark.parametrize("preco", [0, 80, 90, 98, 100, 102, 105, 110, 120, 1e20])
def test_intrinseco_limites_e_monotonicidade(direcao, kv, preco):
    trava = calcular_trava_manual(direcao, 100, 3, kv, 1, contratos=37)
    analise = analisar_cenarios_trava(trava, 100, alvo_ativo=preco)
    cenario = analise["cenarios"][-1]
    sinal = 1 if direcao == "compra" else -1
    # Oracle por pernas para valores usuais; limite exato para precos enormes.
    intrinseco = (max(sinal * (preco - 100), 0) - max(sinal * (preco - kv), 0)
                 if preco < 1e15 else (10 if sinal == 1 else 0))
    assert cenario["valor_intrinseco"] == pytest.approx(intrinseco)
    assert cenario["payoff_liquido"] == pytest.approx(intrinseco - 2)
    assert cenario["pnl_total"] == pytest.approx((intrinseco - 2) * 37)
    assert -74 <= cenario["pnl_total"] <= 296
    pnls = [c["pnl_total"] for c in analise["cenarios"][:5]]
    assert pnls == sorted(pnls, reverse=(sinal == -1))


@pytest.mark.parametrize("direcao,kv", [("compra", 12), ("venda", 10)])
def test_pnl_zero_no_breakeven_sem_arredondar_custo(direcao, kv):
    trava = calcular_trava_manual(direcao, 11, 0.254, kv, 0.081, contratos=37)
    analise = analisar_cenarios_trava(trava, 11)
    resultado = analisar_cenarios_trava(trava, 11, alvo_ativo=analise["breakeven"])
    assert resultado["cenarios"][-1]["pnl_total"] == 0
    assert resultado["custo_liquido"] == 0.173
    assert resultado["risco_maximo"] == pytest.approx(0.173 * 37)


def test_alvo_stop_distancia_e_risco_integral(alta):
    resultado = analisar_cenarios_trava(alta, 95, alvo_ativo=100, stop_ativo=90)
    assert resultado["distancia_strike"] == 5
    assert resultado["distancia_strike_pct"] == pytest.approx(5 / 95 * 100)
    assert resultado["largura"] == 10
    assert [c["nome"] for c in resultado["cenarios"][-2:]] == ["alvo", "stop"]
    # Chegar ao strike comprado nao gera lucro no vencimento.
    assert all(c["pnl_total"] == -74 for c in resultado["cenarios"][-2:])
    assert resultado["risco_maximo"] == resultado["custo_total"] == 74
    assert analisar_cenarios_trava(alta, 105)["distancia_strike"] == -5
    assert len(analisar_cenarios_trava(alta, 100, stop_ativo=0)["cenarios"]) == 6


def test_quantidade_real_sem_default_ou_multiplicador(alta):
    alta["quantidade"] = alta.pop("contratos")
    assert analisar_cenarios_trava(alta, 100)["risco_maximo"] == 74
    alta["contratos"] = 37.0
    assert analisar_cenarios_trava(alta, 100)["contratos"] == 37
    alta["quantidade"] = 100
    with pytest.raises(ValueError, match="coincidir"):
        analisar_cenarios_trava(alta, 100)


@pytest.mark.parametrize("campo", ["strike_comprado", "strike_vendido", "custo_liquido",
                                   "contratos", "quantidade", "premio_comprado", "premio_vendido"])
@pytest.mark.parametrize("valor", [None, True, "2", float("nan"), float("inf"), -float("inf"), 10**1000])
def test_rejeita_dados_nao_numericos_ou_nao_finitos(alta, campo, valor):
    alta[campo] = valor
    with pytest.raises(ValueError):
        analisar_cenarios_trava(alta, 100)


@pytest.mark.parametrize("campo", ["preco_ativo", "alvo_ativo", "stop_ativo"])
@pytest.mark.parametrize("valor", [True, "100", float("nan"), float("inf"), -1])
def test_precos_invalidos(alta, campo, valor):
    argumentos = {"preco_ativo": 100, campo: valor}
    with pytest.raises(ValueError):
        analisar_cenarios_trava(alta, **argumentos)


@pytest.mark.parametrize("mudanca", [
    {"direcao": "venda"}, {"tipo": "put"}, {"direcao": "neutro"},
    {"strike_comprado": 0}, {"strike_vendido": 100}, {"strike_vendido": 90},
    {"custo_liquido": 0}, {"custo_liquido": -1}, {"custo_liquido": 10},
    {"custo_liquido": 11}, {"contratos": 0}, {"contratos": -1}, {"contratos": 1.5},
    {"premio_comprado": -1}, {"premio_vendido": -1}, {"premio_vendido": 0.5},
])
def test_estrutura_invalida(alta, mudanca):
    alta.update(mudanca)
    with pytest.raises(ValueError):
        analisar_cenarios_trava(alta, 100)


@pytest.mark.parametrize("campo", ["direcao", "tipo", "strike_comprado", "strike_vendido",
                                   "custo_liquido", "contratos"])
def test_campo_obrigatorio_ausente(alta, campo):
    del alta[campo]
    with pytest.raises(ValueError):
        analisar_cenarios_trava(alta, 100)


def test_dict_preco_zero_e_overflow(alta):
    for trava, preco in ((None, 100), ([], 100), (alta, 0), (alta, 1.79e308), (alta, 5e-324)):
        with pytest.raises(ValueError):
            analisar_cenarios_trava(trava, preco)
    alta["contratos"] = 10**308
    with pytest.raises(ValueError):
        analisar_cenarios_trava(alta, 100)


def test_totais_sao_recalculados_e_nao_usa_bs(alta, monkeypatch):
    def proibido(*args, **kwargs):
        pytest.fail("Analise nao pode chamar Black-Scholes")
    monkeypatch.setattr("trava._premio_bs_europeu", proibido)
    alta.update(custo_total=1, risco_maximo=1, ganho_maximo=1, breakeven=1,
                stop_premio_total=1, dias_vencimento=0, vol_impl_comprado=None)
    resultado = analisar_cenarios_trava(alta, 100)
    assert resultado["risco_maximo"] == 74
    assert resultado["ganho_maximo"] == 296
    assert resultado["breakeven"] == 102


def test_html_seguro_compacto_e_sem_promessas(alta):
    ataque = '<script>alert("x")</script> & teste'
    alta.update(nome=ataque, fonte=ataque)
    resultado = analisar_cenarios_trava(alta, 100, alvo_ativo=110, stop_ativo=90)
    resultado["cenarios"][0]["nome"] = ataque
    resultado["observacao"] += ataque
    antes = deepcopy(resultado)
    texto = formatar_cenarios_trava(resultado)
    assert resultado == antes
    assert ataque not in texto
    assert texto.count(escape(ataque)) == 4
    assert texto.startswith("<b>")
    assert "37 contratos" in texto
    assert "PnL total R$ +296.00" in texto
    assert "PnL total R$ -74.00" in texto
    assert "NAO valor hoje nem antes do vencimento" in texto
    assert "Sem probabilidades" in texto
    assert "perda de 100% do custo" in texto
    assert "sem taxas, impostos ou slippage" in texto
    assert len(texto) < 2500
