# Auditoria Tecnica do B3-bot

## Escopo

Revisao estatica integral dos 18 modulos Python: `b3_swing_analyzer`, `screener`,
`gestao_risco`, `estado`, `relatorio_diario`, `backtest`, `diario_sinais`,
`posicoes`, `trava`, `fonte_opcoes`, `opcoes`, `ai_analyzer`, `noticias`,
`calendario`, `config`, `telegram_bot`, `servidor_api` e `telegram_utils`.
Tambem revisados workflows, dependencias, scripts de startup, pytest e README.
JSONs operacionais nao foram alterados, nem relatórios reais disparados.

## Conclusao Sobre a Estrategia

O fluxo e coerente como heuristica de apoio a swing trade: identifica direcao,
verifica regime de mercado, limita entradas, define risco e pede segunda opiniao.
Isso nao demonstra vantagem estatistica. RSI, MACD, estocastico e medias derivam
dos mesmos precos; pontuacoes altas nao equivalem a observacoes independentes nem
a probabilidade de lucro. Os thresholds foram preservados, nao otimizados.

Um filtro pode reduzir falsos sinais e tambem excluir operacoes lucrativas.
ADX e medias sao atrasados. O bloqueio dos dois lados em lateralidade/conflito
e uma escolha conservadora, nao uma lei do mercado. Nao e possivel concluir
que teria evitado uma perda especifica sem reconstruir dados e execucoes.

## Correcoes Verificadas por Testes

- Wilder em RSI e ADX/DI; aquecimento sem indicadores ficticios; NaN/inf recusados.
- Sessoes fechadas explicitas, cache separado do parcial e indices temporais validados.
- Bonus horario nao desfaz exaustao; suavizacao nao transfere direcao nem eleva teto.
- Propostas/cancelamentos, resumo, diario e candidatos IA seguem decisao consistente.
- Sizing limitado pelo risco e capital; Kelly sem vantagem nao aumenta risco.
- Trava acompanhada pelo liquido das duas pernas no vencimento e strikes exatos.
- BS diferencia dias uteis/corridos; custo pequeno valido nao e adulterado.
- Fallback estimado limpa identificacao real; ask e usado para custo de compra.
- Precos velhos ou contraditorios conhecidos sao recusados; schemas ambiguos nao passam.
- IA pode discordar; JSON estrito e campos numericos nao viram ordens verificadas.
- Gestao por regras prevalece sobre IA em stop/alvo; sem preco nao ha recomendacao.
- Persistencia local atomica; corrupcao nao vira carteira/historico vazio silenciosamente.
- Proposta expirada ou registro existente nao sobrescreve operacao real.
- Backtest verifica dia de entrada e gaps; agregados nao sao rotulados retorno de capital.
- Diario usa N-esima sessao historica, nao preco de uma execucao arbitraria atrasada.
- Webhook confirma fila limitada, com um worker, dedup atomico e tentativas de envio limitadas.
- Mensagens HTML extensas sao particionadas; requests possuem limites de espera.

## Riscos Ainda Abertos

1. **Sem certificacao de rentabilidade.** Backtest nao replica todos os filtros,
   carteira, custos, aluguel, opcoes, volatilidade implicita ou execucao real.
   Validar fora da amostra e acompanhar em simulacao antes de usar capital.
2. **Dados de terceiros.** Timestamp ausente nao permite certificar atualidade.
   Limite de idade usa dias corridos, nao calendario oficial B3; noticias sao
   heuristicas e podem associar evento a empresa errada. Sem calendario/IBOV,
   a politica existente e prosseguir com aviso, nao bloquear tudo.
3. **Opcoes.** BS e aproximacao sem dividendos/exercicio americano. Referencia de
   fechamento nao e bid/ask executavel; limite teorico exige ambas as pernas
   intactas. Nao existe execucao automatica, stop garantido ou parcial registrada.
4. **Persistencia distribuida.** Atomicidade e locks protegem o processo local,
   nao escritores Render/Actions em paralelo. Confirmar sincronizacao GitHub nos
   logs; snapshots remotos podem estar desatualizados. Propostas sao restauradas
   no startup do Render, nao continuamente; comparar com o relatorio do dia.
5. **Fila volatil.** Reinicio pode perder comando confirmado ou permitir nova
   execucao apos expulsao do cache. Nao ha exactly-once nem fila duravel.
6. **Deploy.** Uma unica instancia/processo e Flask de desenvolvimento; validar
   configuracao real antes de publicar. Sem TELEGRAM_WEBHOOK_SECRET, chat_id nao
   autentica origem. Segredo recomendado, mas opcional para deploy existente.
7. **Datas e eventos corporativos.** Gestao aproxima sessoes por segunda/sexta,
   sem feriados. Historico de acoes ajustado e diario nao ajustado exigem cautela
   em splits/dividendos. Configure fuso de Brasilia. Diario mede direcao, nao PnL.
8. **Dependencias e provedores.** Versoes locais verificadas; disponibilidade de
   modelos, cotas, esquema online das APIs e deploy Python 3.12 nao exercitados.

## Verificacao Reproduzivel

`python -m pytest tests/ -o addopts= -q`

Os testes de auditoria isolam rede e arquivos reais; cenarios sinteticos verificam
matematica e regressao, nao resultados financeiros. Ler o total atual na saida da
suite. `git diff --check` valida whitespace, nao comportamento de producao.

Nenhum commit, push ou deploy faz parte desta auditoria. Publicacao requer revisar
o diff, preparar ambiente de teste e conferir persistencia antes do redeploy.

## Extensao Operacional Posterior

Foram adicionados `setups.py`, `carteira.py`, `selecao_trava.py` e
`cenarios_trava.py`, integrados a relatorio/comandos. A politica padrao agora
separa CANDIDATO de execucao; registro automatico de candidato e recusado.
Ver README para formulas, comandos, thresholds, limites e convencoes de custos.

Essas regras novas estao cobertas por testes sinteticos e integrados, nao por
evidencia de vantagem financeira. Nao foi implementada negociacao automatica,
monitoramento intradiario permanente, ledger de fills ou simulacao de carteira
com opcoes. O diario existente nao mede candidatos como se fossem entradas.
Uma revisao historica fora da amostra e acompanhamento prospectivo continuam
necessarios antes de concluir que a estrategia e lucrativa.

## Revisao Independente das Melhorias

Regressoes reproduzidas e corrigidas apos a primeira implementacao:

- Gatilhos gerados com OHLC ajustado agora respeitam o proximo centavo estritamente
  acima/abaixo do extremo, antes de calcular risco e alvo. Antes podiam ficar
  entre centavos, sem nenhuma cotacao negociavel que atendesse o RR minimo.
- Sem novo padrao, candidato intacto pode sobreviver ao relatorio seguinte na
  validade original. Reuso exige mesma direcao, gates atuais aprovados, historico
  posterior completo e nenhum toque em stop/alvo. Feriados sem candle podem
  impedir reuso por falta de calendario B3 (politica conservadora).
- Datas futuras e setups expirados nao sao republicados como candidatos novos;
  /propostas identifica vencidos pela data do sinal, nao pela ultima gravacao.
- Gestao no relatorio usa fechamentos nao ajustados para todas as acoes abertas,
  como /status. Nao reutiliza precos ajustados dos indicadores contra stops reais.
- Decimal uniformiza debito, largura, breakeven, payoff e orcamento: R$0.07 vezes
  100 cabe em R$7; debito igual a largura nao e uma trava com lucro positivo.
- Backtest preserva retornos/custos sem arredondar cada trade: custos fracionarios
  nao desaparecem antes das estatisticas.

Suite integrada desta revisao: 1642 testes passaram. Um aviso de deprecacao
vem do SDK Google. Sem rede de producao, mudancas em posicoes reais ou deploy.

## Politica de Prazo Curto

Atualizacao apos esclarecer que o operador compra opcoes com ate um mes restante:
novas selecoes exigem 14..30 dias corridos por dt/due_date, mantendo cadeia integral
para gestao das posicoes existentes. BS de simulacao continua disponivel como
funcao matematica, mas nao substitui uma trava real inelegivel no relatorio.

Lateralidade isolada do IBOV nao bloqueia tudo: o screener exige forca/fraqueza
relativa 5/10 sessoes e retorno proprio5d na direcao. Conflito/contratendencia
preservam tetos; dados insuficientes nao liberam a excecao lateral. Thresholds
sao hipoteses conservadoras a validar, nao uma estrategia comprovadamente lucrativa.
