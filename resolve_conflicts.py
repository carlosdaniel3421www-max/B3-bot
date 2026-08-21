import re

# Resolve config.py
with open(r'C:\Users\carlo\Desktop\B3-bot\config.py', 'r', encoding='utf-8') as f:
    content = f.read()

# config.py conflict
old = "<<<<<<< HEAD\nDEEPSEEK_API_KEY = os.environ.get(\"DEEPSEEK_API_KEY\", \"\")\nDEEPSEEK_MODEL = os.environ.get(\"DEEPSEEK_MODEL\", \"deepseek-v4-flash-free\")\nDEEPSEEK_BASE_URL = os.environ.get(\"DEEPSEEK_BASE_URL\", \"https://opencode.ai/zen/v1\")\n=======\nNEMOTRON_API_KEY = os.environ.get(\"NEMOTRON_API_KEY\", \"\")\nNEMOTRON_MODEL = os.environ.get(\"NEMOTRON_MODEL\", \"nemotron-3.5-free\")\nNEMOTRON_BASE_URL = os.environ.get(\"NEMOTRON_BASE_URL\", \"https://opencode.ai/zen/v1\")\n>>>>>>> bb04106 (Troca DeepSeek por Nemotron 3.5 do opencode zen)"

new = """NEMOTRON_API_KEY = os.environ.get("NEMOTRON_API_KEY", "")
NEMOTRON_MODEL = os.environ.get("NEMOTRON_MODEL", "nemotron-3.5-free")
NEMOTRON_BASE_URL = os.environ.get("NEMOTRON_BASE_URL", "https://opencode.ai/zen/v1")"""

if "<<<<<<< HEAD" in content:
    content = content.replace(
        "<<<<<<< HEAD\nDEEPSEEK_API_KEY = os.environ.get(\"DEEPSEEK_API_KEY\", \"\")\nDEEPSEEK_MODEL = os.environ.get(\"DEEPSEEK_MODEL\", \"deepseek-v4-flash-free\")\nDEEPSEEK_BASE_URL = os.environ.get(\"DEEPSEEK_BASE_URL\", \"https://opencode.ai/zen/v1\")\n=======\nNEMOTRON_API_KEY = os.environ.get(\"NEMOTRON_API_KEY\", \"\")\nNEMOTRON_MODEL = os.environ.get(\"NEMOTRON_MODEL\", \"nemotron-3.5-free\")\nNEMOTRON_BASE_URL = os.environ.get(\"NEMOTRON_BASE_URL\", \"https://opencode.ai/zen/v1\")\n>>>>>>> bb04106 (Troca DeepSeek por Nemotron 3.5 do opencode zen)",
        """NEMOTRON_API_KEY = os.environ.get("NEMOTRON_API_KEY", "")
NEMOTRON_MODEL = os.environ.get("NEMOTRON_MODEL", "nemotron-3.5-free")
NEMOTRON_BASE_URL = os.environ.get("NEMOTRON_BASE_URL", "https://opencode.ai/zen/v1")"""
    )
    with open(r'C:\Users\carlo\Desktop\B3-bot\config.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print("config.py resolved")
else:
    print("No conflict markers in config.py")