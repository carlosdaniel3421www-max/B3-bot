"""Risco agregado em memoria, sem cotacoes, persistencia ou envio de ordens.

Os limites controlam somente recomendacoes de novas exposicoes automaticas.
Nao representam garantia de lucro, de execucao do stop ou de perda maxima real.
"""

from datetime import date
from decimal import Decimal
from html import escape
from math import isfinite


def _numero(valor, campo):
    if not isinstance(valor, (int, float)) or isinstance(valor, bool):
        raise ValueError(f"{campo}: informe um numero finito")
    try:
        if not isfinite(valor):
            raise ValueError(f"{campo}: informe um numero finito")
    except OverflowError as erro:
        raise ValueError(f"{campo}: numero fora da faixa suportada") from erro
    return Decimal(str(valor))


def _data(valor, campo):
    try:
        resultado = date.fromisoformat(valor)
        if resultado.isoformat() != valor:
            raise ValueError
        return resultado
    except (TypeError, ValueError) as erro:
        raise ValueError(f"{campo}: informe uma data valida AAAA-MM-DD") from erro


def _float_finito(valor):
    resultado = float(valor)
    if not isfinite(resultado):
        raise ValueError("Calculo fora da faixa numerica suportada")
    return resultado


def avaliar_carteira(posicoes, capital, risco_max_pct=3,
                     exposicao_setor_max_pct=40, mapa_setores=None,
                     data_referencia=None):
    """Avalia um dict {identificador: registro}, sem modificar os argumentos.

    Registro: ticker (opcional, usa identificador), direcao compra/venda,
    tipo_operacao acao (padrao) ou trava, preco_entrada positivo, quantidade
    inteira em unidades (nao lotes) e data_entrada ISO. Acao exige stop positivo,
    <= entrada na compra e >= entrada na venda; igualdade e breakeven (risco 0).
    Trava de debito exige vencimento ISO; risco = preco_entrada * quantidade,
    independentemente do stop. Strikes/premios, quando presentes, sao conferidos.
    Quantidade ausente, None ou zero e desconhecida, nunca uma posicao zerada.

    Capital deve ser positivo; limites percentuais estao entre 0 e 100.
    Parametros globais invalidos e overflow agregado levantam ValueError. Registros ruins
    permanecem em detalhes, com status incompleto e valores indisponiveis None.
    Os agregados sao subtotais dos registros calculaveis, nao risco total certo.

    mapa_setores: dict ticker -> setor. None desativa a verificacao setorial,
    com alerta; mapa parcial torna a avaliacao incompleta. Setores medem apenas
    nominal bruto de ACOES na entrada/capital, sem compensar compra e venda.
    Debitos de travas sao separados, nao equivalem ao nominal do subjacente.

    data_referencia: ISO opcional, nunca usa o relogio. Quando fornecida, rejeita
    entrada futura e exige revisao de travas vencidas (mantendo seu risco).
    Sem ela, valida formato e ordem das datas, mas nao vencimento atual.

    Retorna status completo/incompleto, risco_reais/pct, exposicao_nominal_acao,
    debito_travas, por_direcao, setores (None sem mapa), detalhes, alertas e
    permite_nova_operacao. Limites sao inclusivos, comparados sem arredondar.
    Nao estima margem, aluguel, custos, delta, liquidez nem compensacao de risco.
    """
    if not isinstance(posicoes, dict) or not all(
            isinstance(chave, str) and chave.strip() for chave in posicoes):
        raise ValueError("posicoes deve ser um dict com identificadores textuais")
    capital_d = _numero(capital, "capital")
    risco_limite = _numero(risco_max_pct, "risco_max_pct")
    setor_limite = _numero(exposicao_setor_max_pct, "exposicao_setor_max_pct")
    if capital_d <= 0 or not 0 <= risco_limite <= 100 or not 0 <= setor_limite <= 100:
        raise ValueError("Capital deve ser positivo e limites devem estar entre 0 e 100")
    referencia = None if data_referencia is None else _data(data_referencia, "data_referencia")
    if mapa_setores is not None and (
            not isinstance(mapa_setores, dict) or not all(
                isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip()
                for k, v in mapa_setores.items())):
        raise ValueError("mapa_setores deve ser um dict ticker -> setor nao vazio")

    alertas = [
        "Risco estimado: stops nao garantem execucao; gaps e custos podem ampliar perdas.",
        "Nominal de venda nao e margem disponivel; margem e aluguel nao foram estimados.",
    ]
    if mapa_setores is None:
        alertas.append("Sem mapa de setores: limite setorial nao verificado.")
    if referencia is None:
        alertas.append("Sem data de referencia: vencimento atual e entrada futura nao verificados.")
    detalhes = {}
    setores = {} if mapa_setores is not None else None
    totais = {d: {"risco_reais": Decimal(0), "exposicao_nominal_acao": Decimal(0),
                  "debito_travas": Decimal(0)} for d in ("compra", "venda")}
    completo = True
    for identificador, registro in sorted(posicoes.items()):
        problemas = []
        item = {"ticker": identificador, "direcao": None, "tipo_operacao": None,
                "quantidade": None, "risco_reais": None,
                "exposicao_nominal_acao": None, "debito_travas": None,
                "status": "incompleto", "alertas": problemas}
        detalhes[identificador] = item
        if not isinstance(registro, dict):
            problemas.append("Registro deve ser um dict")
            registro = {}
        ticker = registro.get("ticker", identificador)
        if not isinstance(ticker, str) or not ticker.strip():
            problemas.append("Ticker ausente ou invalido")
        else:
            item["ticker"] = ticker
        direcao = registro.get("direcao")
        tipo = registro.get("tipo_operacao", "acao")
        item.update(direcao=direcao, tipo_operacao=tipo)
        try:
            inicio = _data(registro.get("data_entrada"), "data_entrada")
            if referencia is not None and inicio > referencia:
                problemas.append("Data de entrada futura em relacao a referencia")
            if tipo == "trava":
                vencimento = _data(registro.get("vencimento"), "vencimento")
                if vencimento < inicio:
                    problemas.append("Vencimento anterior a entrada")
                if referencia is not None and vencimento <= referencia:
                    problemas.append("Trava vencida: verifique exercicio/liquidacao; risco mantido")
        except ValueError as erro:
            problemas.append(str(erro))

        setor = None
        if setores is not None and tipo == "acao":
            setor = mapa_setores.get(item["ticker"])
            if setor is None:
                problemas.append("Setor nao informado no mapa; exposicao setorial incompleta")
        item["setor"] = setor
        try:
            if direcao not in ("compra", "venda") or tipo not in ("acao", "trava"):
                raise ValueError("Direcao ou tipo_operacao invalido")
            entrada = _numero(registro.get("preco_entrada"), "preco_entrada")
            if entrada <= 0:
                raise ValueError("preco_entrada deve ser positivo")
            quantidade = registro.get("quantidade")
            if quantidade is None:
                raise ValueError("Quantidade desconhecida; informe as unidades da posicao")
            qtd = _numero(quantidade, "quantidade")
            if qtd < 0 or qtd != qtd.to_integral_value():
                raise ValueError("Quantidade deve ser inteira e nao negativa")
            item["quantidade"] = int(qtd)
            if qtd == 0:
                raise ValueError("Quantidade zero e desconhecida, nao ausencia de exposicao")
            for campo in ("alvo", "prazo_maximo_dias", "stop", "strike_comprado",
                          "strike_vendido", "premio_comprado", "premio_vendido"):
                if campo in registro:
                    valor = _numero(registro[campo], campo)
                    if valor < 0 or (campo != "stop" and campo != "premio_vendido" and valor == 0):
                        raise ValueError(f"{campo}: valor fora da faixa valida")
                    if campo == "prazo_maximo_dias" and valor != valor.to_integral_value():
                        raise ValueError("prazo_maximo_dias deve ser inteiro")
            if tipo == "acao":
                stop = _numero(registro.get("stop"), "stop")
                if stop <= 0 or (direcao == "compra" and stop > entrada) or (
                        direcao == "venda" and stop < entrada):
                    raise ValueError("Stop incoerente com a direcao da acao")
                risco = abs(entrada - stop) * qtd
                nominal, debito = entrada * qtd, Decimal(0)
            else:
                for par in (("strike_comprado", "strike_vendido"),
                            ("premio_comprado", "premio_vendido")):
                    if any(c in registro for c in par):
                        a, b = (_numero(registro.get(c), c) for c in par)
                        if par[0] == "strike_comprado":
                            largura = b - a if direcao == "compra" else a - b
                            if not 0 < entrada < largura:
                                raise ValueError("Debito/strikes incoerentes com a direcao da trava")
                        elif abs((a - b) - entrada) > Decimal("1e-9"):
                            raise ValueError("Premios nao correspondem ao debito registrado")
                risco = debito = entrada * qtd
                nominal = Decimal(0)
            valores = {"risco_reais": risco, "exposicao_nominal_acao": nominal,
                       "debito_travas": debito}
            # Valida todos os resultados antes de incluir a posicao nos subtotais.
            calculados = {campo: _float_finito(valor) for campo, valor in valores.items()}
            item.update(calculados)
            for campo, valor in valores.items():
                totais[direcao][campo] += valor
            if setor is not None:
                grupo = setores.setdefault(setor, {"compra": Decimal(0), "venda": Decimal(0)})
                grupo[direcao] += nominal
        except ValueError as erro:
            problemas.append(str(erro))
        if problemas:
            completo = False
            alertas.extend(f"{identificador}: {p}" for p in problemas)
        else:
            item["status"] = "completo"

    risco = sum(t["risco_reais"] for t in totais.values())
    risco_pct = risco / capital_d * 100
    permite = completo
    if risco > capital_d * risco_limite / 100:
        permite = False
        alertas.append("Risco agregado excede o limite configurado para novas recomendacoes.")
    if setores is not None:
        for setor, grupo in sorted(setores.items()):
            nominal = grupo["compra"] + grupo["venda"]
            if nominal > capital_d * setor_limite / 100:
                permite = False
                alertas.append(f"Setor {setor}: exposicao nominal bruta excede o limite configurado.")
            grupo.update(exposicao_nominal_acao=nominal, exposicao_pct=nominal / capital_d * 100)
            setores[setor] = {k: _float_finito(v) for k, v in grupo.items()}
    if not completo:
        alertas.append("Avaliacao incompleta: valores sao subtotais conhecidos; novas exposicoes automaticas bloqueadas.")
    if any(i["tipo_operacao"] == "trava" for i in detalhes.values()):
        alertas.append("Travas: risco pelo debito integral, nao pelo stop; pressupoe ambas as pernas intactas, antes de custos.")
    return {
        "status": "completo" if completo else "incompleto",
        "capital": _float_finito(capital_d), "data_referencia": data_referencia,
        "risco_max_pct": _float_finito(risco_limite),
        "exposicao_setor_max_pct": _float_finito(setor_limite),
        "risco_reais": _float_finito(risco), "risco_pct": _float_finito(risco_pct),
        "exposicao_nominal_acao": _float_finito(sum(t["exposicao_nominal_acao"] for t in totais.values())),
        "debito_travas": _float_finito(sum(t["debito_travas"] for t in totais.values())),
        "por_direcao": {d: {k: _float_finito(v) for k, v in t.items()} for d, t in totais.items()},
        "setores": setores, "detalhes": detalhes, "alertas": alertas,
        "permite_nova_operacao": permite,
    }


def avaliar_nova_operacao(posicoes, candidato, capital, risco_max_pct=3,
                          exposicao_setor_max_pct=40, mapa_setores=None,
                          data_referencia=None):
    """Simula ADICAO de um registro com ticker, inclusive se ja houver o ativo.

    Nao e atualizacao, fechamento, compensacao nem ordem real. Retorna antes,
    depois, alertas e permite_nova_operacao (ambas as avaliacoes devem permitir).
    Candidato sem dict/ticker valido levanta ValueError; outros erros aparecem
    em depois como incompletude. Nao altera posicoes, candidato ou mapa_setores.
    """
    if (not isinstance(candidato, dict) or not isinstance(candidato.get("ticker"), str)
            or not candidato["ticker"].strip()):
        raise ValueError("Candidato deve ser um registro com ticker valido")
    parametros = dict(capital=capital, risco_max_pct=risco_max_pct,
                      exposicao_setor_max_pct=exposicao_setor_max_pct,
                      mapa_setores=mapa_setores, data_referencia=data_referencia)
    antes = avaliar_carteira(posicoes, **parametros)
    simuladas = dict(posicoes)
    identificador = candidato["ticker"]
    while identificador in simuladas:
        identificador += "#nova"
    simuladas[identificador] = candidato
    depois = avaliar_carteira(simuladas, **parametros)
    return {"antes": antes, "depois": depois,
            "alertas": list(dict.fromkeys(antes["alertas"] + depois["alertas"])),
            "permite_nova_operacao": antes["permite_nova_operacao"] and depois["permite_nova_operacao"]}


def formatar_resumo_carteira(avaliacao):
    """Formata o retorno de avaliar_carteira em HTML seguro, sem efeitos externos."""
    parcial = avaliacao["status"] != "completo"
    linhas = ["<b>Resumo da carteira</b>",
              "Avaliacao incompleta: subtotais conhecidos, nao o risco total." if parcial else "Avaliacao completa dos dados informados.",
              f"Risco estimado: R$ {avaliacao['risco_reais']:.2f} ({avaliacao['risco_pct']:.2f}% do capital).",
              f"Nominal bruto de acoes na entrada: R$ {avaliacao['exposicao_nominal_acao']:.2f}.",
              f"Debito integral de travas: R$ {avaliacao['debito_travas']:.2f}."]
    for direcao, valores in avaliacao["por_direcao"].items():
        linhas.append(escape(f"{direcao}: risco R$ {valores['risco_reais']:.2f}; nominal de acoes R$ {valores['exposicao_nominal_acao']:.2f}; debito de travas R$ {valores['debito_travas']:.2f}."))
    for setor, valores in (avaliacao["setores"] or {}).items():
        linhas.append(escape(f"Setor {setor}: R$ {valores['exposicao_nominal_acao']:.2f} ({valores['exposicao_pct']:.2f}% do capital), somente acoes."))
    for identificador, item in avaliacao["detalhes"].items():
        risco = "indisponivel" if item["risco_reais"] is None else f"R$ {item['risco_reais']:.2f}"
        linhas.append(escape(f"{identificador} ({item['ticker']}): {item['status']}; risco {risco}."))
    linhas.extend(escape(str(alerta)) for alerta in avaliacao["alertas"])
    linhas.append("Novas exposicoes automaticas: " + (
        "dentro dos limites verificados." if avaliacao["permite_nova_operacao"] else "nao recomendar."))
    linhas.append("Somente recomendacoes: nao impede operacoes reais ou manuais. Nao ha garantia de lucro ou de perda limitada.")
    return "\n".join(linhas)
