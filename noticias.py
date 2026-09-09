"""
Módulo de notícias — checa manchetes recentes de um ativo e sinaliza
alertas se encontrar palavras-chave de risco (fraude, recuperação judicial,
processo, rebaixamento, etc).

Fonte: Google News RSS (gratuito, sem necessidade de API key).
Requer internet normal na sua máquina.
"""

import feedparser
import re
import unicodedata
import urllib.parse
import requests

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
# sentido de uma palavra de risco (ex: "nega recuperação judicial").
# Desmentido não comprova ausência de risco; esta é apenas uma heurística local.
PALAVRAS_NEGACAO = [
    " nega ", " negou ", "desmente", "desmentiu", "descarta", "descartou",
    "rejeita", "rejeitou", "arquiva", "arquivou", "improcedente",
    "sem provas", "não confirma", "nao confirma", "nega rumor",
]


def buscar_noticias(nome_busca: str, max_itens: int = 12):
    """
    Busca notícias recentes no Google News para o termo de busca.
    `nome_busca` deve ser o nome da empresa (ex: 'Petrobras'), não o ticker,
    pois o Google News indexa melhor por nome do que por código B3.
    """
    if type(max_itens) is not int or max_itens < 0:
        raise ValueError("max_itens deve ser inteiro não negativo")
    if not isinstance(nome_busca, str) or not nome_busca.strip():
        raise ValueError("nome_busca vazio")
    if max_itens == 0:
        return []
    query = urllib.parse.quote(nome_busca.strip())
    url = f"https://news.google.com/rss/search?q={query}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    resposta = requests.get(url, timeout=15)
    resposta.raise_for_status()
    feed = feedparser.parse(resposta.content)
    if feed.get("bozo"):
        raise ValueError("Feed de notícias inválido; risco não verificado")

    noticias = []
    for entrada in feed.entries[:max_itens]:
        if not isinstance(entrada.get("title"), str) or not entrada["title"].strip():
            continue
        noticias.append({
            "titulo": entrada.title,
            "link": entrada.get("link", ""),
            "publicado": getattr(entrada, "published", ""),
        })
    return noticias


def classificar_noticias(noticias: list) -> dict:
    """Classifica manchetes em alertas de risco e sinais positivos."""
    alertas = []
    positivas = []
    neutralizadas = []  # notícias que bateram palavra de risco, mas com negação (falso-positivo evitado)

    def normalizar(texto):
        return "".join(c for c in unicodedata.normalize("NFKD", texto.casefold())
                       if not unicodedata.combining(c))

    negacoes = "|".join(re.escape(normalizar(n.strip())) for n in PALAVRAS_NEGACAO)
    # Apenas negação imediatamente ligada ao evento; não contamina outra oração.
    negacao_local = re.compile(
        rf"\b(?:{negacoes}|nao|sem)(?:\s+(?:a|o|as|os|de|da|do|que|ha|houve|ter|uma|um|rumor|rumores|sobre|possibilidade))*\s*$"
    )

    def negado(prefixo):
        match = negacao_local.search(prefixo)
        # "Não descarta fraude" não é um desmentido da fraude.
        return match is not None and not re.search(r"\bnao\s*$", prefixo[:match.start()])

    total = 0
    for n in noticias:
        if not isinstance(n, dict) or not isinstance(n.get("titulo"), str) or not n["titulo"].strip():
            continue
        total += 1
        titulo_lower = normalizar(n["titulo"])
        riscos = []
        negados = []
        for palavra in PALAVRAS_RISCO:
            for match in re.finditer(r"\b" + re.escape(normalizar(palavra)) + r"s?\b", titulo_lower):
                (negados if negado(titulo_lower[:match.start()]) else riscos).append(palavra)
        if riscos:
            alertas.append({**n, "motivo": riscos[0]})
            continue
        if negados:
            neutralizadas.append({**n, "motivo": negados[0]})
            continue  # desmentido não é recomendação positiva
        for palavra in PALAVRAS_POSITIVAS:
            matches = list(re.finditer(r"\b" + re.escape(normalizar(palavra)) + r"\b", titulo_lower))
            if matches and not any(negado(titulo_lower[:m.start()]) for m in matches):
                positivas.append({**n, "motivo": palavra})
                break

    return {"alertas": alertas, "positivas": positivas, "neutralizadas": neutralizadas, "total_analisado": total}


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
