#!/bin/bash
# Render: script de inicialização do servidor
set -euo pipefail
export TZ=America/Sao_Paulo
# Reinstala so se faltar dependencia (mesma execucao/container reaproveitado);
# em container novo do plano gratuito, instala tudo de novo.
if ! python -c "import flask, pandas, numpy, matplotlib, mplfinance, feedparser, requests, yfinance, openai, google.genai, schedule" 2>/dev/null; then
  pip install -r requirements.txt
fi
exec python servidor_api.py
