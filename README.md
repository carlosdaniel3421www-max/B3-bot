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
python -m pip install -r requirements.txt
```

## Configuração (uma vez só)

### 1. Telegram
1. No Telegram, converse com **@BotFather** → `/newbot` → siga as instruções → guarde o **TOKEN**.
2. Mande uma mensagem qualquer para o bot que você criou.
3. Rode: `python telegram_utils.py --descobrir-chat-id SEU_TOKEN` para pegar seu **chat_id**.
4. Abra `config.py` e preencha `TELEGRAM_TOKEN` e `TELEGRAM_CHAT_ID`
   (ou defina como variáveis de ambiente `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID`).

### 2. Opções (opcional, mas recomendado)
Travas consultam referencias de fechamento do `opcoes.net.br`. OpLab e opcional
para sugestoes de opcoes. Se nao houver dados utilizaveis, a estrutura estimada
e identificada como teorica: nao garante existencia da serie nem execucao.
Confirme vencimento, codigos, bid/ask e quantidade das duas pernas na corretora.

### 3. Watchlist
Edite `WATCHLIST` em `config.py` (e `NOME_EMPRESA` no mesmo arquivo
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

O placar de 0 a 10 combina tendencia, RSI, MACD, estocastico e suporte/resistencia.
Nao e probabilidade: 8/10 nao significa 80% de chance de lucro. Indicadores
correlacionados nao constituem confirmacoes estatisticamente independentes.

- A partir de 8: candidato a ENTRAR, sujeito a filtros de risco.
- 6 ou 7: AGUARDAR, sem proposta automatica registravel.
- Abaixo de 6: EVITAR; direcao neutra: SEM SINAL.
- Ibovespa em alta limita vendas a 7; em baixa limita compras a 7.
- Ibovespa lateral permite candidatos com movimento proprio e forca relativa
  confirmados em 5/10 sessoes; sem confirmacao limita a direcao a 7.
- Sinais conflitantes do Ibovespa continuam limitando ambos os lados a 7.
- Ibovespa indisponivel: filtro nao aplicado, com aviso explicito.
- Suavizacao nao mistura direcoes e nunca eleva o score acima do sinal atual.
- Noticias/resultados que bloqueiam entrada prevalecem no resumo, proposta e IA.

ADX/DI e RSI usam suavizacao de Wilder. ATR dos stops usa media simples.
O modo diario padrao usa sessoes anteriores a hoje em Brasilia, inclusive quando
executado depois do pregao. Candle parcial e opt-in; nao serve como confirmacao
de fechamento. Falta de calendario nao significa ausencia de evento.

## Telegram e Deploy

GitHub Actions gera o relatorio; Render atende comandos por webhook. `/relatorio`
dispara o workflow, nao executa o relatorio dentro do servidor.
No Render: `bash render_start.sh`. Configure `TZ=America/Sao_Paulo` se usar
diretamente `python servidor_api.py`. O servidor ainda usa Flask de desenvolvimento.

Configure `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`, e as chaves opcionais de IA
`GEMINI_API_KEY`/`CARLOS`. `GITHUB_TOKEN` no Render requer acesso ao repositorio,
Contents read/write para persistencia e Actions write para `/relatorio`.
Nunca publique tokens nem coloque valores reais nos arquivos versionados.

Recomendado: `TELEGRAM_WEBHOOK_SECRET` com 1-256 caracteres alfanumericos, `_` ou
`-`. Reinicie para registrar o segredo no Telegram. Sem esse segredo, o filtro
de chat nao autentica a origem de uma requisicao forjada.

Use uma unica instancia/processo. Webhook confirma apos enfileirar; um worker
serial processa os comandos, com fila limitada e deduplicacao. `/health` verifica
o processo local, `/ready` consulta o registro remoto. Fila/deduplicacao sao em
memoria: reinicio pode perder trabalho aceito; nao ha garantia exactly-once.
Nao ative polling enquanto houver webhook registrado.

JSONs de posicoes/propostas sao persistidos no GitHub, nao em disco duravel do
Render. Escritas locais sao atomicas e protegidas entre threads, mas isso nao
resolve concorrencia entre maquinas. Falhas de sincronizacao exigem conferencia
dos logs e do arquivo remoto. O workflow preserva artefatos se o push falhar.

## Validacao

```bash
python -m pytest tests/ -o addopts= -q
python backtest.py PETR4 --periodo 2y --nivel-minimo 8
```

Backtest simula a acao, sem carteira, custos ou opcoes, e nao replica todos os
filtros do relatorio. Soma de retornos/drawdown dessa soma sao pontos percentuais,
nao rentabilidade do capital. O diario mede direcao na N-esima sessao, nao PnL.
Nao use esses numeros como comprovacao de lucratividade da trava. Thresholds
precisam de validacao fora da amostra e acompanhamento em simulacao.

## Limitações importantes

- **Dados diários (fechamento):** feito para swing trade (dias/semanas), não para day trade intraday.
- **Notícias:** busca por palavras-chave, não é análise de sentimento com IA. Pode ter falso positivo/negativo — sempre dê uma lida na manchete.
- **Strike de opção:** sem a OpLab, é uma sugestão de faixa, não o código exato da opção. Confirme liquidez antes de operar.
- **Nada disso substitui sua própria gestão de risco.** Defina sempre o tamanho de posição de acordo com o que você pode perder.

## Auditoria do Codigo

Consulte `AUDITORIA.md` para escopo revisado, correcoes, limites operacionais
e verificacoes que ainda dependem de dados reais e ambiente de producao.

## Operacao por Setups

`EXIGIR_SETUP=True` e o padrao em `config.py`. Mesmo com score >=8, o ativo agora
precisa de rompimento confirmado ou recuo com retomada. O relatorio produz
**CANDIDATO**, nao uma ordem de entrada imediata. Sem setup ou dados suficientes,
nao fabrica sinal. O filtro pode reduzir muito o numero de oportunidades.

- Rompimento: supera extremo anterior de 20 barras, volume confirmado e medias alinhadas.
- Recuo: toque na SMA21, preservacao da SMA50 e retomada; venda e o espelho.
- Gatilho acima/abaixo do candle fechado, stop estrutural e espaco ate barreira.
- Alvo sem barreira identificada e projecao teorica 2R, nao previsao.
- `/gatilho TICKER PRECO ATR AAAA-MM-DD` confere informacoes fornecidas manualmente.
- Gatilho usa validade de 1 a 4 dias corridos apos sinal; calendario aproximado,
  conferir se existe pregao. Gap alem de 0.5 ATR ou RR deteriorado cancela.
- O comando nao observa mercado em tempo real, nao envia ordem e nao confirma fill.
- `/registrar TICKER` recusa candidatos. Apos executar, registre preco, limites e
  quantidade reais pelo registro manual. Para trava use `/trava_registrar`.

`/carteira` mostra risco conhecido e incompletudes. Limites iniciais: 3% de risco
agregado e 40% de nominal bruto de acoes por setor. Sao hipoteses configuraveis,
nao valores ideais universais. Quantidade zero/ausente significa desconhecida e
bloqueia recomendacoes automaticas. Debito integral e o risco usado nas travas.
O mapa setorial e manual; nao estima correlacao nem delta equivalente das opcoes.
Cada candidato e avaliado individualmente contra posicoes abertas, nao todos
simultaneamente: recalcule antes de abrir uma segunda operacao.

### Opcoes com Ate Um Mes de Vencimento

Novas sugestoes usam **14 a 30 dias corridos**, calculados pela data real do
vencimento, nao pelo campo de dias uteis. O limite de 30 respeita o horizonte
do operador; o minimo de 14 e uma escolha conservadora para nao sugerir novas
entradas nas duas ultimas semanas. Nao e evidencia de prazo otimo ou garantia
de lucro. Posicoes existentes continuam acompanhadas no vencimento registrado.

Sem serie real elegivel, o relatorio nao sugere uma trava mais longa nem a
substitui automaticamente por BS, inclusive no modo legado. A sugestao isolada
de CALL/PUT sem cotacao continua identificada como teorica dentro de 14..30 dias.
`/trava` sem vencimento e somente calculadora: nao certifica esta politica.

Com IBOV lateral, compra exige retorno proprio positivo em 5 sessoes e superar
o indice em 5 e 10 sessoes. Venda exige retorno proprio negativo e ficar abaixo
do indice nas duas janelas. Historicos devem ter as ultimas 11 datas iguais,
validas e fechadas. Dados ausentes/desalinhados bloqueiam a excecao. Nao ha bonus
de score; setup, gatilho, exaustao, risco agregado e liquidez continuam exigidos.
Isso evita esperar obrigatoriamente uma tendencia do indice; nao garante
oportunidades diarias nem que o movimento ocorra antes do vencimento.

Travas automaticas passam a ser selecionadas pela tese na acao, com strikes
entre preco e alvo, breakeven compativel, mesmo vencimento e evidencia temporal
de negocios. Se nenhuma couber no orcamento de R$40 para 100 unidades, o relatorio
informa a ausencia, sem fallback teorico automatico nesse modo.
Os cenarios +/-5%, +/-10%, parado, alvo e stop mostram **payoff no vencimento**,
nao valor para encerrar amanha. Registro e escolha final continuam manuais.

Backtest aceita custos e slippage hipoteticos por lado em basis points:

```bash
python backtest.py PETR4 --periodo 2y --nivel-minimo 8 --custos-bps-por-lado 10 --slippage-bps-por-lado 25
```

Defaults de custos continuam zero para comparacao; nao use zero como expectativa
de execucao. O backtest nao replica os novos setups/carteira e nao e validacao
da rentabilidade deles. Candidatos nao entram no diario antigo como operacoes
executadas. A validacao prospectiva do ciclo de gatilho ainda precisa ser feita
com precos e execucoes registrados; nao se deduz isso de um fechamento diario.
