"""Selecao local de travas de debito pela tese, sem rede ou premio estimado."""

import math
from datetime import date
from decimal import Decimal

from cenarios_trava import analisar_cenarios_trava
from fonte_opcoes import cotacao_utilizavel, _faixa_dias_corridos
from trava import calcular_trava_manual


def selecionar_trava_por_tese(cadeia, preco_ativo, direcao, alvo_ativo,
                              contratos=100, orcamento=40, dias_min=1, dias_max=60, *,
                              dias_corridos_min=None, dias_corridos_max=None):
    """Retorna {trava: dict | None, motivo: str}, sem modificar a cadeia.

    Aceita a cadeia estruturada de fonte_opcoes e direcao compra/call ou
    venda/put (direcao deve ser 'compra' ou 'venda'). Exige dt na politica
    corrida inclusiva (14..30); limites opcionais so estreitam a politica.
    dias_min/dias_max filtram DU adicionalmente. Premios positivos,
    negocios e timestamps verificaveis sao exigidos
    nas duas pernas. Codigo/sufixo e opcional; nao inventa series.

    Strikes: preco <= comprado < vendido <= alvo na alta, simetrico na baixa.
    Nao aplica corte arbitrario de distancia (como 5%). Entre pares viaveis,
    ordena por distancia da comprada ao preco, da vendida ao alvo, custo,
    du e data de vencimento. Nao prioriza premio de R$ 0,25 ou ganho maximo.

    Breakeven estritamente entre preco e alvo, payoff no alvo positivo e
    debito total dentro do orcamento, sem taxas/impostos/slippage. Nenhuma
    garantia de execucao ou lucro antes do vencimento. Entradas invalidas
    ou ausencia de par viavel retornam trava=None e motivo explicativo.
    """
    def numero(valor):
        if valor is None or isinstance(valor, bool):
            return None
        try:
            valor = float(valor)
            return valor if math.isfinite(valor) else None
        except (TypeError, ValueError, OverflowError):
            return None

    try:
        minimo, maximo = _faixa_dias_corridos(dias_corridos_min, dias_corridos_max)
    except ValueError as erro:
        return {"trava": None, "motivo": str(erro)}
    parametros = (preco_ativo, alvo_ativo, contratos, orcamento, dias_min, dias_max)
    if any(not isinstance(v, (int, float)) or numero(v) is None or v <= 0
           for v in parametros):
        return {"trava": None, "motivo": "Parametros devem ser numeros finitos e positivos."}
    if int(contratos) != contratos or dias_min > dias_max:
        return {"trava": None, "motivo": "Contratos devem ser inteiros e dias_min <= dias_max."}
    if not isinstance(direcao, str) or direcao.lower() not in ("compra", "venda"):
        return {"trava": None, "motivo": "Direcao deve ser compra ou venda."}
    direcao = direcao.lower()
    sinal = 1 if direcao == "compra" else -1
    preco, alvo, limite = (Decimal(str(v)) for v in (preco_ativo, alvo_ativo, orcamento))
    if sinal * (alvo - preco) <= 0:
        return {"trava": None, "motivo": "Alvo deve estar no sentido da tese a partir do preco."}
    if not isinstance(cadeia, dict) or not isinstance(cadeia.get("expirations"), (list, tuple)):
        return {"trava": None, "motivo": "Cadeia estruturada indisponivel."}

    melhor = None
    melhor_ordem = None
    lado_nome = "calls" if sinal == 1 else "puts"
    hoje = date.today()
    for venc in cadeia["expirations"]:
        if not isinstance(venc, dict):
            continue
        du = numero(venc.get("du"))
        try:
            dias_corridos = (date.fromisoformat(venc.get("dt")) - hoje).days
        except (TypeError, ValueError):
            continue
        if not minimo <= dias_corridos <= maximo or du is None or not dias_min <= du <= dias_max:
            continue
        lado = venc.get(lado_nome)
        if not isinstance(lado, dict):
            continue
        pernas = []
        for strike, info in lado.items():
            strike = numero(strike)
            if strike is None or strike <= 0 or not isinstance(info, dict):
                continue
            if not 0 <= sinal * (Decimal(str(strike)) - preco) <= sinal * (alvo - preco):
                continue
            premio = numero(info.get("preco"))
            negocios = numero(info.get("negocios"))
            if premio is None or premio <= 0 or negocios is None or negocios <= 0:
                continue
            # cotacao_utilizavel tolera ausencia de datas; aqui exigimos evidencia.
            if not info.get("data_hora") or not cadeia.get("data_ultimo_pregao"):
                continue
            if not cotacao_utilizavel(info, cadeia):
                continue
            if "strike" in info and numero(info["strike"]) != strike:
                continue
            pernas.append((strike, premio, info))

        for comprado, premio_c, info_c in pernas:
            for vendido, premio_v, info_v in pernas:
                kc, kv, pc, pv = (Decimal(str(v)) for v in (comprado, vendido, premio_c, premio_v))
                largura = sinal * (kv - kc)
                debito = pc - pv
                total = debito * int(contratos)
                breakeven = kc + sinal * debito
                payoff = min(max(sinal * (alvo - kc), 0), largura) - debito
                if (not 0 < debito < largura or total > limite
                        or not 0 < sinal * (breakeven - preco) < sinal * (alvo - preco)
                        or payoff <= 0):
                    continue
                try:
                    trava = calcular_trava_manual(
                        direcao, comprado, premio_c, vendido, premio_v,
                        contratos=int(contratos), gasto_maximo=orcamento)
                    analise = analisar_cenarios_trava(trava, preco_ativo, alvo_ativo)
                except (ValueError, OverflowError):
                    continue
                ordem = (abs(kc - preco), abs(kv - alvo), total, du, venc["dt"])
                if melhor_ordem is not None and ordem >= melhor_ordem:
                    continue

                # Completa o schema de montar_trava, sem sua busca por premio/BS
                # nem suas sugestoes de lucro/saida antecipada pelo strike.
                trava.pop("compensa")
                trava.pop("relacao_risco_retorno")
                trava.update(
                    breakeven=analise["breakeven"],
                    premio_comprado_total=float(pc * int(contratos)),
                    encerrar_quando=None,
                    dias_vencimento=du,
                    dias_corridos=dias_corridos,
                    vencimento_data=venc["dt"],
                    stop_premio_por_contrato=None,
                    stop_premio_total=None,
                    lucro_alvo_total=None,
                    dias_max_holding=None,
                    fonte="real",
                    alvo_ativo=alvo_ativo,
                    payoff_alvo_vencimento=analise["cenarios"][-1]["payoff_liquido"],
                    pnl_alvo_vencimento=analise["cenarios"][-1]["pnl_total"],
                    observacao=(
                        "Premios observados na cadeia, nao bid/ask executavel. "
                        "Breakeven e payoff no alvo valem somente no vencimento; "
                        "nao garantem lucro antes do vencimento. Sem taxas, impostos "
                        "ou slippage. Confirme cotacoes e liquidez das duas pernas. "
                        "Risco integral: perda de 100% do debito."
                    ),
                )
                for perna, info in (("comprado", info_c), ("vendido", info_v)):
                    trava["sufixo_" + perna] = info.get("sufixo") or ""
                    for campo in ("vol_impl", "delta", "negocios", "volume"):
                        trava[campo + "_" + perna] = numero(info.get(campo))
                melhor, melhor_ordem = trava, ordem

    if melhor is None:
        return {"trava": None, "motivo": (
            f"Nenhum par real viavel no mesmo vencimento entre {minimo} e {maximo} "
            "dias corridos e na faixa de DU: "
            "exigidos premios positivos, negocios, timestamps utilizaveis, strikes "
            "entre preco e alvo, 0 < debito < largura, orcamento, breakeven entre "
            "preco e alvo e payoff positivo no alvo no vencimento."
        )}
    return {"trava": melhor, "motivo": (
        "Par real selecionado pela menor distancia da comprada ao preco e da "
        "vendida ao alvo, dentro do orcamento. "
        f"Vencimento em {melhor['dias_corridos']} dias corridos "
        f"(politica: {minimo} a {maximo}). Payoff positivo no alvo somente "
        "no vencimento; nao implica lucro antes do vencimento."
    )}
