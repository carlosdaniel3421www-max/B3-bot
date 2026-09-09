#!/bin/bash
# Render: script de inicialização do servidor
set -euo pipefail
export TZ=America/Sao_Paulo
pip install -r requirements.txt
exec python servidor_api.py
