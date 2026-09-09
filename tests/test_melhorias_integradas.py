"""Fluxos com setup obrigatorio, servicos mockados e persistencia em memoria."""

from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest

import carteira
import cenarios_trava
import diario_sinais
import fonte_opcoes
import posicoes
import relatorio_diario as rd
import selecao_trava
import telegram_bot as bot
import trava


@pytest.fixture
def ambiente(monkeypatch):
    class DataFixa(date):
        @classmethod
        def today(cls):
            return cls(2030, 1, 8)

    def proibido(*args, **kwargs):
        pytest.fail("I/O real proibido neste teste")

    for modulo in (rd, bot, posicoes, fonte_opcoes, selecao_trava):
        monkeypatch.setattr(modulo, "date", DataFixa)
    monkeypatch.setattr("requests.sessions.Session.request", proibido)
    monkeypatch.setattr("socket.socket.connect", proibido)
    monkeypatch.setattr("socket.create_connection", proibido)
    monkeypatch.setattr(posicoes, "_sincronizar_github", proibido)
    monkeypatch.setattr(rd.config, "EXIGIR_SETUP", True)
    monkeypatch.setattr(rd.config, "CAPITAL_DISPONIVEL", 10000)
    monkeypatch.setattr(rd.config, "RISCO_MAX_CARTEIRA_PCT", 3)
    monkeypatch.setattr(rd.config, "EXPOSICAO_MAX_SETOR_PCT", 40)
    monkeypatch.setattr(rd.config, "SETORES", {"PETR4": "petroleo", "VALE3": "mineracao"})

    # Copias nas fronteiras simulam leitura/gravacao sem abrir nenhum JSON.
    outro = dict(direcao="compra", preco_entrada=10, stop=9, alvo=12)
    dados = {posicoes.CAMINHO_POSICOES: {}, posicoes.CAMINHO_PROPOSTAS: {
        "PETR4": dict(outro, ticker="PETR4", data_proposta="2030-01-08"), "OUTRO": outro,
    }}
    monkeypatch.setattr(posicoes, "_carregar_json", lambda caminho: deepcopy(dados[caminho]))
    gravar = Mock(side_effect=lambda caminho, registros: dados.update({caminho: deepcopy(registros)}))
    monkeypatch.setattr(posicoes, "_salvar_json", gravar)

    plano = dict(setup="rompimento", estado="candidato", motivo="Aguardar gatilho",
                 direcao="compra", data_sinal="2030-01-07", gatilho=10.1,
                 stop=9.1, alvo=12.1, risco_retorno=2.0, alvo_teorico=True,
                 risco_retorno_min=2.0, distancia_max_atr=0.5)
    resultado = dict(ticker="PETR4", score=9, direcao="compra", preco=10.0,
                     motivos=["Tendencia alinhada"], df=pd.DataFrame([{
                         "ema21": 10, "ema200": 9, "rsi": 60, "macd": 0.1,
                         "volume": 1000, "atr": 0.3, "suporte": 9, "resistencia": 12,
                     }]))
    monkeypatch.setattr(rd, "classificar_setup", Mock(return_value=plano))
    monkeypatch.setattr(rd, "rodar_screener", Mock(return_value=[resultado]))
    monkeypatch.setattr(rd, "validar_configuracao", Mock())
    monkeypatch.setattr(rd, "avaliar_regime_ibov", Mock(return_value={"regime": "indisponivel"}))
    monkeypatch.setattr(rd.os, "makedirs", Mock())
    monkeypatch.setattr(rd, "plotar_grafico", Mock())
    monkeypatch.setattr(rd, "carregar_estado", Mock(return_value={}))
    monkeypatch.setattr(rd, "salvar_estado", Mock())
    monkeypatch.setattr(rd, "montar_gestao_posicoes", Mock(return_value=""))
    monkeypatch.setattr(rd, "enviar_album", Mock())
    monkeypatch.setattr(rd, "enviar_mensagem", Mock())
    monkeypatch.setattr(rd.time, "sleep", Mock())
    monkeypatch.setattr(rd, "_montar_analisador_ia", Mock(return_value=None))
    monkeypatch.setattr(rd, "checar_risco_noticias", Mock(return_value={
        "bloquear_entrada": False, "noticias": [],
    }))
    monkeypatch.setattr(rd, "checar_resultado_proximo", Mock(return_value={"tem_resultado_proximo": False}))
    monkeypatch.setattr(rd, "sugerir_stop_alvo", Mock(side_effect=proibido))
    monkeypatch.setattr(rd, "sugerir_parametros_opcao_com_preco", Mock(return_value={
        "tipo_opcao": "CALL", "strike_sugerido_aprox": 10,
        "vencimento_sugerido": "2030-01-25", "premio": 0.6,
    }))
    monkeypatch.setattr(rd, "calcular_tamanho_posicao", Mock(return_value={
        "quantidade_acoes": 100, "valor_posicao": 1010,
        "valor_em_risco": 100, "pct_capital_em_risco": 1,
    }))
    monkeypatch.setattr(diario_sinais, "registrar_sinal", Mock())
    monkeypatch.setattr(diario_sinais, "atualizar_resultados", Mock())
    cadeia = {"data_ultimo_pregao": "2030-01-07", "expirations": [{
        "dt": "2030-01-25", "du": 13, "calls": {
            strike: {"preco": premio, "negocios": 10, "data_hora": "2030-01-07T17:00:00"}
            for strike, premio in ((10, 0.6), (11, 0.4), (12, 0.3))
        },
    }]}
    monkeypatch.setattr(fonte_opcoes, "buscar_cadeia_estruturada", Mock(return_value=cadeia))
    monkeypatch.setattr(trava, "montar_trava", Mock(side_effect=proibido))
    monkeypatch.setattr(selecao_trava, "selecionar_trava_por_tese", Mock(wraps=selecao_trava.selecionar_trava_por_tese))
    monkeypatch.setattr(rd, "avaliar_nova_operacao", Mock(wraps=carteira.avaliar_nova_operacao))
    monkeypatch.setattr(cenarios_trava, "analisar_cenarios_trava", Mock(wraps=cenarios_trava.analisar_cenarios_trava))
    return SimpleNamespace(dados=dados, gravar=gravar, plano=plano, resultado=resultado, cadeia=cadeia, outro=deepcopy(outro))


def executar(nivel_detalhe=6):
    rd.gerar_e_enviar_relatorio(watchlist=["PETR4"], nivel_detalhe=nivel_detalhe)
    return "\n".join(chamada.args[2] for chamada in rd.enviar_mensagem.call_args_list)


@pytest.mark.parametrize("nivel_detalhe", [6, 10])
def test_candidato_persiste_plano_mas_nunca_entrar_ou_registro(ambiente, nivel_detalhe):
    texto = executar(nivel_detalhe)
    assert ambiente.resultado["estado_entrada"] == "candidato"
    assert ambiente.resultado["veredito"]["veredito"] == "CANDIDATO"
    assert "CANDIDATOS (aguardar gatilho)" in texto
    assert "ENTRAR" not in texto
    assert "/registrar PETR4" not in texto
    assert "/gatilho PETR4" in texto
    diario_sinais.registrar_sinal.assert_not_called()
    diario_sinais.atualizar_resultados.assert_called_once_with({})
    proposta = posicoes.carregar_propostas()["PETR4"]
    assert proposta["plano_setup"] == ambiente.plano
    assert proposta["estado_entrada"] == "candidato"
    assert (proposta["preco_entrada"], proposta["stop"], proposta["alvo"]) == (10.1, 9.1, 12.1)
    assert proposta["data_proposta"] == "2030-01-08"
    assert posicoes.carregar_propostas()["OUTRO"] == ambiente.outro
    assert "plano_tecnico" in ambiente.resultado
    assert "Estrutura candidata" in texto
    antes = deepcopy(ambiente.dados)
    ambiente.gravar.reset_mock()
    registrada, motivo = posicoes.registrar_da_proposta("petr4", quantidade=100)
    assert registrada is None
    assert "Candidato aguardando gatilho" in motivo
    assert "Candidato aguardando gatilho" in bot.processar_comando("token", 1, "/registrar PETR4 100")
    assert "CANDIDATO" in bot.processar_comando("token", 1, "/propostas")
    assert ambiente.dados == antes
    ambiente.gravar.assert_not_called()


@pytest.mark.parametrize("estado", ["aguardar", "cancelado"])
def test_sem_setup_bloqueia_e_remove_proposta_antiga(ambiente, estado):
    ambiente.plano.update(estado=estado, setup=None, motivo="Sem padrao <valido>")
    texto = executar()
    assert ambiente.resultado["entrada_permitida"] is False
    assert ambiente.resultado["veredito"]["veredito"] == "EVITAR"
    assert "Setup: Sem padrao &lt;valido&gt;" in texto
    assert "ENTRAR" not in texto
    assert posicoes.carregar_propostas() == {"OUTRO": ambiente.outro}
    diario_sinais.registrar_sinal.assert_not_called()
    fonte_opcoes.buscar_cadeia_estruturada.assert_not_called()
    rd.sugerir_stop_alvo.assert_not_called()


@pytest.mark.parametrize("quantidade", [None, 0])
def test_carteira_incompleta_bloqueia_candidato_e_comando_avisa(ambiente, quantidade):
    ambiente.dados[posicoes.CAMINHO_POSICOES]["VALE3"] = dict(
        direcao="compra", preco_entrada=10, stop=9, quantidade=quantidade,
        data_entrada="2030-01-07")
    texto = executar()
    assert ambiente.resultado["entrada_permitida"] is False
    assert "Carteira incompleta" in texto
    assert posicoes.carregar_propostas() == {"OUTRO": ambiente.outro}
    diario_sinais.registrar_sinal.assert_not_called()
    fonte_opcoes.buscar_cadeia_estruturada.assert_not_called()
    antes = deepcopy(ambiente.dados)
    resumo = bot.processar_comando("token", 1, "/carteira@MeuBot")
    assert "Avaliacao incompleta" in resumo
    assert "subtotais conhecidos" in resumo
    assert "nao recomendar" in resumo
    assert "VALE3" in resumo
    assert ambiente.dados == antes


def test_trava_pela_tese_usa_debito_integral_e_cenarios_reais(ambiente):
    texto = executar()
    selecao_trava.selecionar_trava_por_tese.assert_called_once_with(ambiente.cadeia, 10.0, "compra", 12.1)
    trava.montar_trava.assert_not_called()
    estrutura, preco, alvo, stop = cenarios_trava.analisar_cenarios_trava.call_args.args
    assert (preco, alvo, stop) == (10.0, 12.1, 9.1)
    assert (estrutura["strike_comprado"], estrutura["strike_vendido"]) == (10, 12)
    assert estrutura["custo_liquido"] == pytest.approx(0.3)
    assert estrutura["contratos"] == 100
    chamadas = rd.avaliar_nova_operacao.call_args_list
    assert len(chamadas) == 2  # Acao e opcoes sao exposicoes distintas.
    assert chamadas[0].args[1]["preco_entrada"] == 10.1
    candidato = chamadas[1].args[1]
    assert candidato == dict(ticker="PETR4", tipo_operacao="trava", direcao="compra",
                            preco_entrada=0.3, quantidade=100, vencimento="2030-01-25",
                            data_entrada="2030-01-08")
    risco = carteira.avaliar_nova_operacao(*chamadas[1].args)
    assert risco["permite_nova_operacao"] is True
    assert risco["depois"]["risco_reais"] == 30
    assert risco["depois"]["debito_travas"] == 30
    assert risco["depois"]["exposicao_nominal_acao"] == 0
    assert "Payoff no vencimento" in texto
    assert "Risco integral R$ 30.00" in texto
    assert "alvo (" in texto and "stop (" in texto
    assert "depende do gatilho na acao" in texto


def test_sizing_acao_fora_limite_avisa_sem_bloquear_estrutura_opcoes(ambiente):
    rd.calcular_tamanho_posicao.return_value.update(quantidade_acoes=1000)
    texto = executar()
    assert "Acao com a quantidade sugerida excede limites" in texto
    assert ambiente.resultado["estado_entrada"] == "candidato"
    assert posicoes.carregar_propostas()["PETR4"]["estado_entrada"] == "candidato"
    assert "Estrutura candidata" in texto
    assert "trava bloqueada" not in texto
    diario_sinais.registrar_sinal.assert_not_called()


def test_trava_bloqueada_pelo_risco_agregado_nao_exibe_cenarios(ambiente):
    ambiente.dados[posicoes.CAMINHO_POSICOES]["VALE3"] = dict(
        direcao="compra", preco_entrada=10, stop=8, quantidade=140,
        data_entrada="2030-01-07")
    texto = executar()
    assert ambiente.resultado["estado_entrada"] == "candidato"
    risco = carteira.avaliar_nova_operacao(*rd.avaliar_nova_operacao.call_args.args)
    assert risco["antes"]["risco_reais"] == 280
    assert risco["antes"]["permite_nova_operacao"] is True
    assert risco["depois"]["risco_reais"] == 310
    assert risco["permite_nova_operacao"] is False
    assert "trava bloqueada pelos limites/dados da carteira" in texto
    assert "Payoff no vencimento" not in texto
    cenarios_trava.analisar_cenarios_trava.assert_not_called()


def test_sem_par_real_nao_faz_fallback_teorico(ambiente):
    fonte_opcoes.buscar_cadeia_estruturada.return_value = {}
    texto = executar()
    assert "sem trava adequada a tese" in texto
    trava.montar_trava.assert_not_called()
    cenarios_trava.analisar_cenarios_trava.assert_not_called()


def test_posicao_no_mesmo_ativo_impede_segunda_proposta(ambiente):
    ambiente.dados[posicoes.CAMINHO_POSICOES]["PETR4"] = dict(
        direcao="compra", preco_entrada=10, stop=9, quantidade=100,
        data_entrada="2030-01-07")
    antes = deepcopy(posicoes.carregar_posicoes())
    texto = executar()
    assert ambiente.resultado["entrada_permitida"] is False
    assert "Ja existe posicao neste ativo" in texto
    assert posicoes.carregar_propostas() == {"OUTRO": ambiente.outro}
    assert posicoes.carregar_posicoes() == antes
    diario_sinais.registrar_sinal.assert_not_called()
    fonte_opcoes.buscar_cadeia_estruturada.assert_not_called()


@pytest.mark.parametrize("filtro", ["noticias", "resultados"])
def test_setup_nao_contorna_bloqueios_de_eventos(ambiente, filtro):
    if filtro == "noticias":
        rd.checar_risco_noticias.return_value = {
            "bloquear_entrada": True, "alertas": [{"motivo": "Evento de risco"}],
        }
    else:
        rd.checar_resultado_proximo.return_value = {
            "tem_resultado_proximo": True, "dias_ate_resultado": 1,
            "data_resultado": "2030-01-09",
        }
    texto = executar()
    assert ambiente.resultado["entrada_permitida"] is False
    assert "CANCELADO" in texto
    assert "ENTRAR" not in texto
    rd.classificar_setup.assert_not_called()
    diario_sinais.registrar_sinal.assert_not_called()
    fonte_opcoes.buscar_cadeia_estruturada.assert_not_called()
    assert posicoes.carregar_propostas() == {"OUTRO": ambiente.outro}


@pytest.mark.parametrize("preco,estado", [(10.0, "AGUARDAR"), (10.1, "CANDIDATO"), (11, "CANCELADO")])
def test_gatilho_manual_nao_promove_proposta_nem_registra(ambiente, preco, estado):
    executar()
    antes = deepcopy(ambiente.dados)
    ambiente.gravar.reset_mock()
    texto = bot.processar_comando("token", 1, f"/gatilho@MeuBot petr4 {preco} 1 2030-01-08")
    assert f"PETR4: {estado}" in texto
    assert "MANUAIS" in texto
    assert "nao cotacao certificada nem execucao" in texto
    assert "/carteira" in texto
    assert "ENTRAR" not in texto
    assert posicoes.registrar_da_proposta("PETR4", 100)[0] is None
    assert ambiente.dados == antes
    ambiente.gravar.assert_not_called()


@pytest.mark.parametrize("comando,trecho", [
    ("/gatilho", "Uso:"),
    ("/gatilho OUTRO 10.1 1 2030-01-08", "Sem candidato com setup"),
    ("/gatilho PETR4 10.1 1 2030-01-07", "nao use precos antigos"),
    ("/gatilho PETR4 10.1 1 2030-01-09", "Informe a data de hoje"),
    ("/gatilho PETR4 abc 1 2030-01-08", "Dados invalidos"),
    ("/gatilho PETR4 10.1 1 invalida", "Dados invalidos"),
    ("/gatilho PETR4 nan 1 2030-01-08", "CANCELADO"),
])
def test_gatilho_rejeita_dados_ausentes_antigos_ou_invalidos(ambiente, comando, trecho):
    executar()
    antes = deepcopy(ambiente.dados)
    ambiente.gravar.reset_mock()
    assert trecho in bot.processar_comando("token", 1, comando)
    assert ambiente.dados == antes
    ambiente.gravar.assert_not_called()
