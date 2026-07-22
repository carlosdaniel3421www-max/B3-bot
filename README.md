# B3 Swing Trade Analyzer — Robô de Apoio à Análise Técnica

Ferramenta de apoio para swing trade de ações/opções na B3: analisa gráfico
por confluência técnica, varre vários ativos, checa notícias de risco antes
de confirmar um sinal, sugere stop/alvo e strike/vencimento de opção, e
manda tudo pronto no seu Telegram.

⚠️ **Isto não é recomendação de investimento.** É uma ferramenta que aplica
regras técnicas que você definiu. A decisão e o risco são sempre seus.

## Arquivos

| Arquivo | O que faz |
|---|---|
| `b3_swing_analyzer.py` | Núcleo: baixa dados, calcula indicadores, gera placar de confluência, plota gráfico, calcula stop/alvo |
| `noticias.py` | Busca notícias recentes (Google News) e alerta sobre risco/eventos negativos |
| `telegram_utils.py` | Envia mensagens e gráficos para o Telegram |
| `opcoes.py` | Sugere strike/vencimento de opção; integração opcional com API da OpLab |
| `screener.py` | Varre uma lista de ativos e ranqueia os melhores setups |
| `config.py` | Suas chaves de API e preferências (watchlist, nomes de empresas, etc) |
| `relatorio_diario.py` | Orquestra tudo e manda o relatório completo no Telegram |

## Instalação

```bash
pip install yfinance pandas numpy matplotlib feedparser requests
```

## Configuração (uma vez só)

### 1. Telegram
1. No Telegram, converse com **@BotFather** → `/newbot` → siga as instruções → guarde o **TOKEN**.
2. Mande uma mensagem qualquer para o bot que você criou.
3. Rode: `python telegram_utils.py --descobrir-chat-id SEU_TOKEN` para pegar seu **chat_id**.
4. Abra `config.py` e preencha `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`
   (ou defina como variáveis de ambiente `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID`).

### 2. Opções (opcional, mas recomendado)
A B3 não tem API gratuita boa para cadeia de opções. Recomendo criar conta na
**OpLab** (oplab.com.br) e preencher `OPLAB_TOKEN` em `config.py`. Sem isso,
a ferramenta ainda funciona — só te dá o strike/vencimento *ideal* pra você
procurar manualmente no home broker, em vez de já vir com o código exato da opção.

### 3. Watchlist
Edite `WATCHLIST_PADRAO` em `screener.py` (ou `NOME_EMPRESA` em `config.py`
se adicionar ativos novos, para a busca de notícias funcionar por nome da empresa).

## Uso

**Analisar um ativo específico, na hora:**
```bash
python b3_swing_analyzer.py PETR4 --periodo 1y
```

**Rodar o relatório diário completo (screener + notícias + Telegram):**
```bash
python relatorio_diario.py
```

**Automatizar para rodar todo dia sozinho** (Linux/Mac, via cron), por
exemplo às 10:15 em dias úteis (após a abertura do pregão):
```bash
crontab -e
# adicione a linha:
15 10 * * 1-5 cd /caminho/do/projeto && /usr/bin/python3 relatorio_diario.py
```
No Windows, use o **Agendador de Tarefas** apontando para o mesmo comando.

## Como o placar de confluência funciona

Cada indicador vota +1 (viés de compra) ou -1 (viés de venda):
tendência (médias móveis), RSI, MACD, estocástico, proximidade de
suporte/resistência. Placar ≥ +2 = possível compra. Placar ≤ -2 = possível
venda. Entre -1 e +1 = sem confluência suficiente, a ferramenta não sugere
nada. Você pode reajustar os pesos e regras em `gerar_placar()` dentro de
`b3_swing_analyzer.py` para bater com o seu estilo.

## Limitações importantes

- **Dados diários (fechamento):** feito para swing trade (dias/semanas), não para day trade intraday.
- **Notícias:** busca por palavras-chave, não é análise de sentimento com IA. Pode ter falso positivo/negativo — sempre dê uma lida na manchete.
- **Strike de opção:** sem a OpLab, é uma sugestão de faixa, não o código exato da opção. Confirme liquidez antes de operar.
- **Nada disso substitui sua própria gestão de risco.** Defina sempre o tamanho de posição de acordo com o que você pode perder.
