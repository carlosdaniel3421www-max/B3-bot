"""
Módulo de notícias — checa manchetes recentes de um ativo e sinaliza
alertas se encontrar palavras-chave de risco (fraude, recuperação judicial,
processo, rebaixamento, etc).

Fonte: Google News RSS (gratuito, sem necessidade de API key).
Requer internet normal na sua máquina.
"""

import feedparser
import urllib.parse

# Palavras-chave que costumam indicar risco/eventos negativos relevantes.
# Ajuste essa lista livremente para o seu gosto.
PALAVRAS_RISCO = [
    "recuperação judicial", "falência", "fraude", "investigação",
    "operação da polícia federal", "rebaixamento", "rebaixada",
    "processo judicial", "multa da cvm", "cvm multa", "escândalo",
    "demissão em massa", "greve", "vazamento", "acidente",
    "prejuízo", "queda de lucro", "corte de dividendos",
    "renúncia", "cfo deixa", "ceo deixa", "saída do ceo",
    "auditoria", "irregularidade", "suspensão de negociação",
]

PALAVRAS_POSITIVAS = [
    "recorde de lucro", "aumento de dividendos", "upgrade",
    "elevação de rating", "recompra de ações", "novo contrato",
    "expansão", "fusão", "aquisição estratégica",
]

# Palavras que, quando aparecem na mesma manchete, invertem ou anulam o
# sentido de uma palavra de risco (ex: "nega recuperação judicial" é o
# OPOSTO de estar em recuperação judicial). Detecção simples por presença
# na frase — não é 100% à prova de falhas, mas cobre os casos mais comuns.
PALAVRAS_NEGACAO = [
    "nega", "negou", "desmente", "desmentiu", "descarta", "descartou",
    "rejeita", "rejeitou", "arquiva", "arquivou", "improcedente",
    "sem provas", "não confirma", "nao confirma", "nega rumor",
]


def buscar_noticias(nome_busca: str, max_itens: int = 12):
    """
    Busca notícias recentes no Google News para o termo de busca.
    `nome_busca` deve ser o nome da empresa (ex: 'Petrobras'), não o ticker,
    pois o Google News indexa melhor por nome do que por código B3.
    """
    query = urllib.parse.quote(nome_busca)
    url = f"https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    feed = feedparser.parse(url)

    noticias = []
    for entrada in feed.entries[:max_itens]:
        noticias.append({
            "titulo": entrada.title,
            "link": entrada.link,
            "publicado": getattr(entrada, "published", ""),
        })
    return noticias


def classificar_noticias(noticias: list) -> dict:
    """Classifica manchetes em alertas de risco e sinais positivos."""
    alertas = []
    positivas = []
    neutralizadas = []  # notícias que bateram palavra de risco, mas com negação (falso-positivo evitado)

    for n in noticias:
        titulo_lower = n["titulo"].lower()
        tem_negacao = any(neg in titulo_lower for neg in PALAVRAS_NEGACAO)

        for palavra in PALAVRAS_RISCO:
            if palavra in titulo_lower:
                if tem_negacao:
                    neutralizadas.append({**n, "motivo": palavra})
                else:
                    alertas.append({**n, "motivo": palavra})
                break
        for palavra in PALAVRAS_POSITIVAS:
            if palavra in titulo_lower:
                positivas.append({**n, "motivo": palavra})
                break

    return {"alertas": alertas, "positivas": positivas, "neutralizadas": neutralizadas, "total_analisado": len(noticias)}


def checar_risco_noticias(nome_busca: str) -> dict:
    """
    Busca notícias e retorna classificação + contexto bruto
    para a camada de inteligência artificial.
    """

    noticias = buscar_noticias(nome_busca)

    resultado = classificar_noticias(
        noticias
    )


    # Mantém as manchetes completas
    # para o Gemini analisar contexto

    resultado["noticias"] = noticias


    resultado["bloquear_entrada"] = (
        len(resultado["alertas"]) > 0
    )


    return resultado

if __name__ == "__main__":
    import sys
    nome = sys.argv[1] if len(sys.argv) > 1 else "Petrobras"
    r = checar_risco_noticias(nome)
    print(f"Notícias analisadas: {r['total_analisado']}")
    print(f"Alertas de risco: {len(r['alertas'])}")
    for a in r["alertas"]:
        print(f"  ⚠️  [{a['motivo']}] {a['titulo']}")
    print(f"Sinais positivos: {len(r['positivas'])}")
    for p in r["positivas"]:
        print(f"  ✅ [{p['motivo']}] {p['titulo']}")
