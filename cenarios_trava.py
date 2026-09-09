"""Cenarios deterministas de travas de debito, sem I/O ou precificacao temporal."""

import math
from decimal import Decimal
from html import escape


def analisar_cenarios_trava(trava, preco_ativo, alvo_ativo=None, stop_ativo=None):
    """Analisa diretamente o dict de montar_trava, sem altera-lo.

    Campos obrigatorios: direcao (compra/venda), tipo (call/put),
    strike_comprado, strike_vendido, custo_liquido e contratos. Aceita
    quantidade no lugar de contratos; se ambos existem, devem coincidir.
    Quantidade e inteira e positiva, sem multiplicador de lote implicito.
    Premios das pernas, quando presentes, devem concordar com o debito.
    Totais e breakeven sao recalculados, nao copiados dos campos derivados.

    Preco atual deve ser positivo. Alvo/stop sao precos nao negativos ou
    None (omitidos), sem exigir lado: sao hipoteses, nao ordens de saida.
    Dados numericos usados devem ser int/float finitos, nunca bool ou texto.
    Dados invalidos ou resultados nao finitos levantam ValueError.

    Retorna dict com limites, distancia assinada ate o strike comprado
    (strike - preco, percentual em pontos percentuais) e lista cenarios:
    variacao_pct, preco_ativo, valor_intrinseco por contrato, payoff_liquido
    por contrato e pnl_total. Valores nao sao arredondados no calculo.
    Liquido significa descontado o debito, sem taxas, impostos ou slippage.
    Nao calcula valor hoje, valor antes do vencimento ou probabilidades.
    """
    if not isinstance(trava, dict):
        raise ValueError("trava deve ser um dicionario")

    def numero(valor, campo):
        try:
            valido = (isinstance(valor, (int, float))
                      and not isinstance(valor, bool) and math.isfinite(valor))
        except OverflowError:
            valido = False
        if not valido:
            raise ValueError(f"{campo} deve ser um numero finito")
        return Decimal(str(valor))

    def saida(valor, campo):
        valor = float(valor)
        if not math.isfinite(valor):
            raise ValueError(f"{campo} deve ser um numero finito")
        return valor

    direcao = trava.get("direcao")
    tipo = trava.get("tipo")
    if (direcao, tipo) not in (("compra", "call"), ("venda", "put")):
        raise ValueError("Exigido compra/call (bull call) ou venda/put (bear put)")
    sinal = 1 if direcao == "compra" else -1
    comprado = numero(trava.get("strike_comprado"), "strike_comprado")
    vendido = numero(trava.get("strike_vendido"), "strike_vendido")
    custo = numero(trava.get("custo_liquido"), "custo_liquido")
    preco = numero(preco_ativo, "preco_ativo")
    contratos = numero(trava.get("contratos", trava.get("quantidade")), "contratos")
    if contratos <= 0 or int(contratos) != contratos:
        raise ValueError("contratos deve ser inteiro positivo")
    if "quantidade" in trava:
        quantidade = numero(trava["quantidade"], "quantidade")
        if quantidade != contratos:
            raise ValueError("quantidade e contratos devem coincidir")
    contratos = int(contratos)
    if min(comprado, vendido, preco) <= 0:
        raise ValueError("Strikes e preco_ativo devem ser positivos")
    largura = sinal * (vendido - comprado)
    for campo in ("premio_comprado", "premio_vendido"):
        if campo in trava and numero(trava[campo], campo) < 0:
            raise ValueError(f"{campo} nao pode ser negativo")
    if "premio_comprado" in trava and "premio_vendido" in trava:
        debito = (numero(trava["premio_comprado"], "premio_comprado")
                  - numero(trava["premio_vendido"], "premio_vendido"))
        # O dict publico usa float; valida essa representacao, mas calcula pelas pernas.
        if saida(debito, "debito") != float(custo):
            raise ValueError("Premios das pernas incompativeis com custo_liquido")
        custo = debito
    if not 0 < custo < largura:
        raise ValueError("Exigido 0 < custo_liquido < largura, com strikes na direcao correta")

    breakeven = comprado + sinal * custo
    custo_total = custo * contratos
    ganho_maximo = (largura - custo) * contratos
    distancia = comprado - preco
    distancia_pct = distancia / preco * 100
    pontos = [(f"{pct:+d}%" if pct else "0%", preco * (100 + pct) / 100, pct)
              for pct in (-10, -5, 0, 5, 10)]
    for nome, valor in (("alvo", alvo_ativo), ("stop", stop_ativo)):
        if valor is not None:
            valor = numero(valor, nome + "_ativo")
            if valor < 0:
                raise ValueError(f"{nome}_ativo nao pode ser negativo")
            pontos.append((nome, valor, (valor - preco) / preco * 100))

    cenarios = []
    for nome, valor, variacao in pontos:
        # Forma limitada evita subtrair dois intrinsecos enormes quase iguais.
        intrinseco = min(max(sinal * (valor - comprado), 0), largura)
        payoff = intrinseco - custo
        cenario = {
            "nome": nome,
            "variacao_pct": variacao,
            "preco_ativo": valor,
            "valor_intrinseco": intrinseco,
            "payoff_liquido": payoff,
            "pnl_total": payoff * contratos,
        }
        cenarios.append({campo: saida(v, campo) if campo != "nome" else v
                         for campo, v in cenario.items()})

    resultado = {
        "nome": str(trava.get("nome", "Bull Call Spread" if sinal == 1 else "Bear Put Spread")),
        "fonte": str(trava.get("fonte", "nao informada")),
        "direcao": direcao,
        "tipo": tipo,
        "preco_ativo": preco,
        "strike_comprado": comprado,
        "strike_vendido": vendido,
        "contratos": contratos,
        "largura": largura,
        "custo_liquido": custo,
        "custo_total": custo_total,
        "risco_maximo": custo_total,
        "ganho_maximo": ganho_maximo,
        "breakeven": breakeven,
        "distancia_strike": distancia,
        "distancia_strike_pct": distancia_pct,
        "cenarios": cenarios,
        "observacao": (
            "Payoff liquido no vencimento, NAO valor hoje nem antes do vencimento. "
            "Sem probabilidades. Desconta apenas o debito; sem taxas, impostos ou slippage. "
            "Alvo/stop sao precos hipoteticos no vencimento, nao garantia de saida. "
            "Risco integral: perda de 100% do custo; stop nao reduz esse limite."
        ),
    }
    return {campo: saida(valor, campo) if isinstance(valor, Decimal) else valor
            for campo, valor in resultado.items()}


def formatar_cenarios_trava(analise):
    """Formata o retorno de analisar_cenarios_trava em HTML compacto e escapado."""
    linhas = [
        f"{analise['nome']} | Payoff no vencimento",
        f"{analise['direcao']}/{analise['tipo']} | {analise['contratos']} contratos "
        f"| Ativo R$ {analise['preco_ativo']:.2f} | Fonte premios: {analise['fonte']}",
        f"Strikes compra/venda: {analise['strike_comprado']:.2f}/{analise['strike_vendido']:.2f} "
        f"| Largura R$ {analise['largura']:.2f}",
        f"Custo R$ {analise['custo_liquido']:.4f}/contrato "
        f"| Total R$ {analise['custo_total']:.2f}",
        f"Risco integral R$ {analise['risco_maximo']:.2f} "
        f"| Ganho max. R$ {analise['ganho_maximo']:.2f} "
        f"| Breakeven R$ {analise['breakeven']:.4f}",
        f"Distancia ao strike comprado: R$ {analise['distancia_strike']:+.2f} "
        f"({analise['distancia_strike_pct']:+.2f}%)",
    ]
    for cenario in analise["cenarios"]:
        linhas.append(
            f"{cenario['nome']} ({cenario['variacao_pct']:+.2f}%): "
            f"ativo R$ {cenario['preco_ativo']:.2f} "
            f"| PnL total R$ {cenario['pnl_total']:+.2f}"
        )
    linhas.append(str(analise["observacao"]))
    linhas = [escape(linha, quote=True) for linha in linhas]
    linhas[0] = f"<b>{linhas[0]}</b>"
    linhas[-1] = f"<i>{linhas[-1]}</i>"
    return "\n".join(linhas)
