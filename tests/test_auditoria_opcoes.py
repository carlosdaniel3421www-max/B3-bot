"""Auditoria financeira e persistencia: dados sinteticos, sem rede/JSON real."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
from threading import Event
from unittest.mock import Mock

import pytest

import fonte_opcoes as fonte
import opcoes
import posicoes as p
import trava

SINCRONIZAR_ORIGINAL = p._sincronizar_github


class Hoje(date):
    @classmethod
    def today(cls):
        return cls(2026, 9, 8)


@pytest.fixture(autouse=True)
def isolado(monkeypatch, tmp_path):
    def bloquear(*args, **kwargs):
        pytest.fail("Rede proibida")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("requests.sessions.Session.request", bloquear)
    monkeypatch.setattr("socket.socket.connect", bloquear)
    monkeypatch.setattr("socket.create_connection", bloquear)
    monkeypatch.setattr(p, "CAMINHO_POSICOES", str(tmp_path / "posicoes.json"))
    monkeypatch.setattr(p, "CAMINHO_PROPOSTAS", str(tmp_path / "propostas.json"))
    monkeypatch.setattr(p, "_sincronizar_github", Mock(return_value=True))
    for modulo in (p, fonte, opcoes, trava):
        monkeypatch.setattr(modulo, "date", Hoje)
    fonte.limpar_cache_cadeia()
    yield
    fonte.limpar_cache_cadeia()


def cadeia(calls=None):
    return {"data_ultimo_pregao": "2026-09-04", "expirations": [{
        "dt": "2026-09-25", "du": 13, "mensal": True,
        "calls": calls if calls is not None else {
            11.0: {"preco": 0.25, "negocios": 10, "sufixo": "J11", "vol_impl": 35.2},
            12.0: {"preco": 0.08, "negocios": 20, "sufixo": "J12", "vol_impl": 34.8}},
        "puts": {}}]}


def registro_trava():
    return p.adicionar_trava("TEST4", "compra", 11, 0.25, 12, 0.08,
                             0.085, 0.5, vencimento="2026-09-25")


def test_bs_dias_uteis_base_252():
    esperado = trava._premio_bs_europeu(100, 100, 1, 0.105, 0.30, "call")
    assert trava.estimar_premio(100, 100, 252, "call") == round(esperado, 2)


@pytest.mark.parametrize("tipo,s,k,esperado", [("call", 12, 10, 2), ("put", 8, 10, 2), ("call", 8, 10, 0)])
def test_bs_vencimento_intrinseco(tipo, s, k, esperado):
    assert trava.estimar_premio(s, k, 0, tipo) == esperado


def test_bs_vol_zero_limite_deterministico():
    assert trava._premio_bs_europeu(12, 10, 1, 0, 0, "call") == 2


@pytest.mark.parametrize("valor", [float("nan"), float("inf")])
def test_bs_nao_finito(valor):
    with pytest.raises(ValueError):
        trava.estimar_premio(10, 11, 30, "call", sigma=valor)


@pytest.mark.parametrize("direcao,strike,lado", [("compra", 11, "calls"), ("venda", 9, "puts")])
def test_cadeia_uma_perna_fallback_sem_metadados_reais(direcao, strike, lado):
    dados = cadeia({})
    dados["expirations"][0][lado] = {strike: {
        "preco": 0.25, "negocios": 50, "volume": 999,
        "sufixo": "REAL", "delta": 0.3, "vol_impl": 35}}
    resultado = trava.montar_trava(10, direcao, cadeia_real=dados, ticker="TEST4")
    assert resultado["fonte"] == "estimativa"
    assert resultado["dias_vencimento"] == 13
    assert resultado["vencimento_data"] is None
    assert resultado["dias_corridos"] is None
    for campo in ("sufixo", "delta", "vol_impl", "negocios", "volume"):
        assert resultado[campo + "_comprado"] is None
        assert resultado[campo + "_vendido"] is None
    assert "REAL" not in trava.formatar_trava(resultado, 10)


def test_cadeia_real_nao_escolhe_itm_por_premio_alvo():
    dados = cadeia()
    dados["expirations"][0]["calls"][9] = {"preco": 0.25, "negocios": 100}
    assert trava.montar_trava(10, "compra", cadeia_real=dados, ticker="TEST4")["strike_comprado"] > 10


def test_formatacao_vi_percentual_e_volume_ausente():
    resultado = trava.montar_trava(10, "compra", cadeia_real=cadeia(), ticker="TEST4")
    texto = trava.formatar_trava(resultado, 10)
    assert "35.2%" in texto and "3520" not in texto
    assert "N/D" in texto


def test_stop_meio_centavo_nao_vira_debito_inteiro():
    dados = cadeia({11: {"preco": 0.02, "negocios": 10}, 12: {"preco": 0.01, "negocios": 10}})
    resultado = trava.montar_trava(10, "compra", cadeia_real=dados, ticker="TEST4")
    assert resultado["stop_premio_por_contrato"] == 0.005
    assert resultado["stop_premio_total"] == 0.5


@pytest.mark.parametrize("contratos", [True, 0.5, -1])
def test_contratos_invalidos(contratos):
    with pytest.raises(ValueError):
        trava.montar_trava(10, "compra", contratos=contratos)
    with pytest.raises(ValueError):
        trava.calcular_trava_manual("compra", 11, 0.25, 12, 0.08, contratos=contratos)


def test_zero_alvo_explicito_nao_substituido_por_default():
    with pytest.raises(ValueError):
        trava.montar_trava(10, "compra", premio_alvo_perna1=0)


@pytest.mark.parametrize("du,dt", [(0, "2026-09-08"), (-1, "2026-09-07"), (80, "2027-01-01"),
                                    (None, "2026-09-25"), (float("nan"), "2026-09-25"), (30, "invalida")])
def test_vencimento_fora_faixa_nao_e_fallback(du, dt):
    dados = cadeia()
    dados["expirations"][0].update(du=du, dt=dt)
    assert fonte.buscar_melhor_vencimento(dados) is None


def test_parser_series_curtas_nao_quebram(monkeypatch):
    raw = cadeia()
    raw["expirations"][0]["calls"] = [["J11", 0, "A", 11], [], None, ["J12", 0, "A", "nan"]]
    raw["expirations"][0]["puts"] = []
    monkeypatch.setattr(fonte, "buscar_cadeia_opcoesnet", lambda *a, **k: raw)
    lado = fonte.buscar_cadeia_estruturada("TEST4")["expirations"][0]["calls"]
    assert list(lado) == [11]
    assert lado[11]["preco"] is None
    assert lado[11]["negocios"] is None


def test_parser_usa_schema_reordenado(monkeypatch):
    raw = cadeia()
    raw["columns"] = [{"id": c} for c in ("preco", "strike", "negocios", "data_hora", "vol_impl")]
    raw["expirations"][0].update(calls=[[0.25, 11, 12, "2026-09-04", 35.2]], puts=[])
    monkeypatch.setattr(fonte, "buscar_cadeia_opcoesnet", lambda *a, **k: raw)
    info = fonte.buscar_cadeia_estruturada("TEST4")["expirations"][0]["calls"][11]
    assert info["preco"] == 0.25 and info["negocios"] == 12
    assert info["vol_impl"] == 35.2 and info["data_hora"] == "2026-09-04"


def test_parser_schema_desconhecido_nao_inventa_indices(monkeypatch):
    raw = cadeia()
    raw["columns"] = [{"id": "desconhecido"}]
    monkeypatch.setattr(fonte, "buscar_cadeia_opcoesnet", lambda *a, **k: raw)
    assert fonte.buscar_cadeia_estruturada("TEST4") is None


def test_parser_strike_duplicado_nao_sobrescreve_serie(monkeypatch):
    raw = cadeia()
    raw["expirations"][0].update(calls=[["A", 0, "A", 11], ["B", 0, "E", 11]], puts=[])
    monkeypatch.setattr(fonte, "buscar_cadeia_opcoesnet", lambda *a, **k: raw)
    assert fonte.buscar_cadeia_estruturada("TEST4")["expirations"][0]["calls"] == {}


@pytest.mark.parametrize("valor", [True, "nan", "inf", "-inf"])
def test_parser_rejeita_nao_finito(valor):
    assert fonte._to_float(valor) is None


@pytest.mark.parametrize("mudanca", ["sem_negocio", "perna_antiga", "cadeia_antiga", "futura", "preco_acima_largura"])
def test_gestao_rejeita_fechamento_inutilizavel(monkeypatch, mudanca):
    registro = registro_trava()
    dados = cadeia()
    info = dados["expirations"][0]["calls"][11]
    if mudanca == "sem_negocio":
        info["negocios"] = 0
    elif mudanca == "perna_antiga":
        info["data_hora"] = "2026-08-31T17:00:00"
    elif mudanca == "cadeia_antiga":
        dados["data_ultimo_pregao"] = "2026-08-01"
    elif mudanca == "futura":
        dados["data_ultimo_pregao"] = "2026-09-09"
    else:
        info["preco"] = 2
    monkeypatch.setattr(fonte, "buscar_cadeia_estruturada", lambda *a: dados)
    assert p._buscar_premio_trava("TEST4", registro) is None


def test_busca_premio_pula_strike_sem_negocio(monkeypatch):
    dados = cadeia()
    dados["expirations"][0]["calls"][11]["negocios"] = 0
    monkeypatch.setattr(fonte, "buscar_cadeia_estruturada", lambda *a: dados)
    assert fonte.buscar_premio_real("TEST4", 11, "call")["strike_real"] == 12


def test_oplab_compra_ask_nao_bid_e_preserva_vencimento(monkeypatch):
    cotacao = {"type": "CALL", "strike": 10.5, "days_to_maturity": 17,
               "due_date": "2026-09-25", "ask": 0.30, "bid": 0.10, "volume": 100}
    monkeypatch.setattr(opcoes, "buscar_cadeia_oplab", lambda *a: [cotacao])
    resultado = opcoes.sugerir_parametros_opcao_com_preco(10, "compra", "TEST4", token="fake")
    assert resultado["premio"] == 0.30
    assert resultado["vencimento_sugerido"] == "2026-09-25"
    assert resultado["strike_sugerido_aprox"] == 10.5


@pytest.mark.parametrize("campo,valor", [("ask", -1), ("ask", float("nan")), ("ask", None),
    ("bid", 0.5), ("volume", 0), ("strike", float("inf")), ("due_date", "2020-01-01")])
def test_oplab_recusa_cotacao_invalida(campo, valor):
    cotacao = {"type": "CALL", "strike": 11, "days_to_maturity": 17,
               "due_date": "2026-09-25", "ask": 0.3, "bid": 0.1, "volume": 10}
    cotacao[campo] = valor
    assert opcoes.escolher_melhor_opcao([cotacao], 11, "CALL") == {}


def test_opcao_sem_token_tem_estimativa_corrida_explicita():
    resultado = opcoes.sugerir_parametros_opcao_com_preco(100, "compra", "TEST4")
    esperado = round(trava._premio_bs_europeu(100, 103, 22 / 365, 0.105, 0.30, "call"), 2)
    assert resultado["premio"] == esperado
    assert resultado["fonte"] == "estimativa"
    assert "nao e cotacao" in resultado["observacao"]


@pytest.mark.parametrize("preco,direcao,minimo,maximo", [(float("nan"), "compra", 25, 45),
    (10, "neutro", 25, 45), (10, "compra", 45, 25), (10, "compra", 0, 45)])
def test_opcao_parametros_invalidos(preco, direcao, minimo, maximo):
    with pytest.raises(ValueError):
        opcoes.sugerir_parametros_opcao(preco, direcao, minimo, maximo)


@pytest.mark.parametrize("arquivo,carregar,adicionar", [
    ("CAMINHO_POSICOES", p.carregar_posicoes, lambda: p.adicionar_posicao("TEST4", "compra", 10, 9, 12)),
    ("CAMINHO_PROPOSTAS", p.carregar_propostas, lambda: p.salvar_proposta_entrada("TEST4", "compra", 10, 9, 12))])
@pytest.mark.parametrize("conteudo", ['{"TEST4":', '[]', '{"TEST4": null}',
                                      '{"TEST4": {"valor": 1}, "TEST4": {"valor": 2}}'])
def test_json_corrompido_nao_vira_carteira_vazia(arquivo, carregar, adicionar, conteudo):
    caminho = Path(getattr(p, arquivo))
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ValueError):
        carregar()
    with pytest.raises(ValueError):
        adicionar()
    assert caminho.read_text(encoding="utf-8") == conteudo
    p._sincronizar_github.assert_not_called()


@pytest.mark.parametrize("salvar,caminho", [(p.salvar_posicoes, "CAMINHO_POSICOES"), (p.salvar_propostas, "CAMINHO_PROPOSTAS")])
@pytest.mark.parametrize("falha", ["serializacao", "replace"])
def test_gravacao_falha_preserva_arquivo(monkeypatch, salvar, caminho, falha):
    salvar({"ANTIGO": {"valor": 1}})
    arquivo = Path(getattr(p, caminho))
    original = arquivo.read_bytes()
    p._sincronizar_github.reset_mock()
    if falha == "replace":
        monkeypatch.setattr(p.os, "replace", Mock(side_effect=OSError("disco")))
        dados = {"NOVO": {"valor": 2}}
    else:
        dados = {"NOVO": {"valor": float("nan")}}
    with pytest.raises((ValueError, OSError)):
        salvar(dados)
    assert arquivo.read_bytes() == original
    assert list(arquivo.parent.iterdir()) == [arquivo]
    p._sincronizar_github.assert_not_called()


def test_duas_threads_nao_perdem_posicao(monkeypatch):
    leu = Event()
    liberar = Event()
    carregar = p.carregar_posicoes
    chamadas = []
    def leitura_lenta():
        dados = carregar()
        chamadas.append(1)
        if len(chamadas) == 1:
            leu.set()
            assert liberar.wait(5)
        return dados
    monkeypatch.setattr(p, "carregar_posicoes", leitura_lenta)
    with ThreadPoolExecutor(max_workers=2) as executor:
        primeira = executor.submit(p.adicionar_posicao, "AAA4", "compra", 10, 9, 12)
        assert leu.wait(5)
        segunda = executor.submit(p.adicionar_posicao, "BBB4", "compra", 10, 9, 12)
        try:
            # Sem lock a segunda termina enquanto a primeira ainda tem snapshot vazio.
            from concurrent.futures import TimeoutError
            with pytest.raises(TimeoutError):
                segunda.result(timeout=0.1)
        finally:
            liberar.set()
        primeira.result(timeout=5)
        segunda.result(timeout=5)
    assert set(carregar()) == {"AAA4", "BBB4"}


def test_proposta_nao_reescreve_trava():
    original = registro_trava()
    p.salvar_proposta_entrada("TEST4", "compra", 10, 9, 12)
    resultado, mensagem = p.registrar_da_proposta("TEST4")
    assert resultado == original
    assert p.carregar_posicoes()["TEST4"] == original
    assert "preservada" in mensagem


@pytest.mark.parametrize("data_proposta", ["2020-01-01", "2026-09-09", "invalida", None])
def test_proposta_expirada_ou_futura_nao_registra(data_proposta):
    proposta = p.salvar_proposta_entrada("TEST4", "compra", 10, 9, 12)
    proposta["data_proposta"] = data_proposta
    p.salvar_propostas({"TEST4": proposta})
    assert p.registrar_da_proposta("TEST4")[0] is None
    assert p.carregar_posicoes() == {}


@pytest.mark.parametrize("campo,valor", [("quantidade", -1), ("quantidade", 0.5),
    ("stop", 11), ("alvo", 9), ("prazo_maximo_dias", 0), ("direcao", "neutro")])
def test_proposta_legada_valida_antes_de_registrar(campo, valor):
    proposta = p.salvar_proposta_entrada("TEST4", "compra", 10, 9, 12)
    quantidade = valor if campo == "quantidade" else 100
    if campo != "quantidade":
        proposta[campo] = valor
    p.salvar_propostas({"TEST4": proposta})
    with pytest.raises(ValueError):
        p.registrar_da_proposta("TEST4", quantidade)
    assert p.carregar_posicoes() == {}


def test_proposta_atual_registra_quantidade():
    p.salvar_proposta_entrada("TEST4", "compra", 10, 9, 12)
    registro, _ = p.registrar_da_proposta("TEST4", 100)
    assert registro["quantidade"] == 100 and registro["data_entrada"] == "2026-09-08"


def test_limites_nao_colapsam_por_arredondamento():
    registro = p.adicionar_posicao("TEST4", "compra", 1.004, 1.003, 1.005)
    assert registro["stop"] < registro["preco_entrada"] < registro["alvo"]


def test_alvo_trava_impossivel():
    with pytest.raises(ValueError):
        p.adicionar_trava("TEST4", "compra", 11, 0.25, 12, 0.08, 0.085, 1.01)


def test_atualizacao_nao_reinicia_prazo():
    registro = p.adicionar_posicao("TEST4", "compra", 10, 9, 12)
    registro["data_entrada"] = "2026-09-01"
    p.salvar_posicoes({"TEST4": registro})
    atualizado = p.adicionar_posicao("TEST4", "compra", 10, 9, 13)
    assert atualizado["data_entrada"] == "2026-09-01"


@pytest.mark.parametrize("inicio,esperado", [("2026-09-08", 0), ("2026-09-07", 1), ("2026-09-04", 2)])
def test_prazo_seg_sex_sem_dia_ficticio(inicio, esperado):
    registro = p.adicionar_posicao("TEST4", "compra", 10, 9, 12, prazo_maximo_dias=1)
    registro["data_entrada"] = inicio
    gestao = p.gerar_gestao_posicao(registro, 10)
    assert gestao["dias_uteis"] == esperado
    assert (gestao["acao"] == "FECHAR POR TEMPO") == (esperado >= 1)


@pytest.mark.parametrize("inicio", ["invalida", "2026-09-09", None])
def test_data_invalida_nao_simula_entrada_hoje(inicio):
    registro = p.adicionar_posicao("TEST4", "compra", 10, 9, 12)
    registro["data_entrada"] = inicio
    with pytest.raises(ValueError):
        p.gerar_gestao_posicao(registro, 10)


def test_parcial_e_apenas_sugestao_nao_execucao():
    registro = p.adicionar_posicao("TEST4", "compra", 10, 9, 12, quantidade=100)
    antes = deepcopy(registro)
    assert p.gerar_gestao_posicao(registro, 11.5)["acao"] == "FECHAR PARCIAL"
    assert registro == antes and p.carregar_posicoes()["TEST4"] == antes


def test_premios_fracionarios_preservam_debito_e_risco():
    manual = trava.calcular_trava_manual("compra", 11, 0.254, 12, 0.081)
    registro = p.adicionar_trava("TEST4", "compra", 11, 0.254, 12, 0.081, 0.08, 0.5)
    assert manual["custo_liquido"] == registro["preco_entrada"] == 0.173
    assert manual["risco_maximo"] == 17.3
    assert registro["premio_comprado"] - registro["premio_vendido"] == pytest.approx(0.173)
    assert p.gerar_gestao_trava(registro, 0.173)["lucro_pct"] == 0


@pytest.mark.parametrize("campo,valor", [("quantidade", 0.5), ("prazo_maximo_dias", 0),
    ("premio_comprado", -1), ("premio_vendido", -1), ("premio_vendido", 0.15),
    ("alvo", 2), ("vencimento", "invalida")])
def test_trava_persistida_incoerente_nao_recomenda(campo, valor):
    registro = registro_trava()
    registro[campo] = valor
    assert p.gerar_gestao_trava(registro, 0.3)["acao"] == "INDISPONÍVEL"


def test_strike_chave_prevalece_sobre_campo_interno(monkeypatch):
    dados = cadeia()
    dados["expirations"][0]["calls"][11]["strike"] = 99
    monkeypatch.setattr(fonte, "buscar_cadeia_estruturada", lambda *a: dados)
    assert fonte.buscar_premio_real("TEST4", 11, "call")["strike_real"] == 11


def test_fixture_antiga_tem_preco_na_data_correta(monkeypatch):
    import test_fonte_opcoes as legado
    class DiaDaFixture(date):
        @classmethod
        def today(cls):
            return cls(2026, 8, 24)
    monkeypatch.setattr(fonte, "date", DiaDaFixture)
    legado.test_buscar_premio_real()
    fonte.limpar_cache_cadeia()
    legado.test_buscar_premio_real_put()


def test_fixture_antiga_nao_finge_cotacao_atual(monkeypatch):
    import test_fonte_opcoes as legado
    resposta = Mock(status_code=200)
    resposta.json.return_value = legado._mock_payload()
    monkeypatch.setattr(fonte.requests, "get", Mock(return_value=resposta))
    assert fonte.buscar_premio_real("CMIG4", 10.5, "call") is None


def test_sigma_antiga_nao_contamina_estimativa(monkeypatch):
    dados = cadeia()
    dados["data_ultimo_pregao"] = "2026-01-01"
    for info in dados["expirations"][0]["calls"].values():
        info["vol_impl"] = 200
    estimar = Mock(wraps=trava.estimar_premio)
    monkeypatch.setattr(trava, "estimar_premio", estimar)
    resultado = trava.montar_trava(10, "compra", cadeia_real=dados, ticker="TEST4", sigma=0.3)
    assert resultado["fonte"] == "estimativa"
    assert all(c.args[4] == 0.3 for c in estimar.call_args_list)


def test_gestao_ticker_ausente_nao_quebra_bloco():
    registro = p.adicionar_posicao("TEST4", "compra", 10, 9, 12)
    del registro["ticker"]
    assert "indispon" in p.formatar_gestao_todas({"TEST4": registro}, {"TEST4": 10})


def test_rr_arredondado_nao_libera_abaixo_de_dois():
    resultado = trava.calcular_trava_manual("compra", 10, 0.4, 10.899, 0.1)
    assert resultado["relacao_risco_retorno"] == 2.0
    assert resultado["ganho_maximo"] < resultado["risco_maximo"] * 2
    assert resultado["compensa"] is False


@pytest.mark.parametrize("status", [403, 500])
def test_sincronizacao_get_falhou_nao_tenta_put(monkeypatch, status):
    p.salvar_posicoes({"TEST4": {"valor": 1}})
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    get = Mock(return_value=Mock(status_code=status))
    put = Mock()
    monkeypatch.setattr(p.requests, "get", get)
    monkeypatch.setattr(p.requests, "put", put)
    assert SINCRONIZAR_ORIGINAL(p.CAMINHO_POSICOES) is False
    assert get.call_args.kwargs["params"] == {"ref": p.BRANCH_GITHUB}
    put.assert_not_called()


def test_sincronizacao_conflito_nao_reenvia_cegamente(monkeypatch):
    p.salvar_posicoes({"TEST4": {"valor": 1}})
    original = Path(p.CAMINHO_POSICOES).read_bytes()
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    get = Mock(return_value=Mock(status_code=200, json=lambda: {"sha": "versao-original"}))
    put = Mock(return_value=Mock(status_code=409))
    monkeypatch.setattr(p.requests, "get", get)
    monkeypatch.setattr(p.requests, "put", put)
    assert SINCRONIZAR_ORIGINAL(p.CAMINHO_POSICOES) is False
    assert put.call_count == 1 and get.call_count == 1
    assert put.call_args.kwargs["json"]["sha"] == "versao-original"
    assert Path(p.CAMINHO_POSICOES).read_bytes() == original


def test_falha_remota_e_visivel_e_preserva_local(monkeypatch, caplog):
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    monkeypatch.setattr(p, "_sincronizar_github", Mock(return_value=False))
    p.salvar_posicoes({"TEST4": {"valor": 1}})
    assert p.carregar_posicoes() == {"TEST4": {"valor": 1}}
    assert "NAO persistido" in caplog.text
