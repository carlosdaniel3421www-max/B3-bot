with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'r', encoding='utf-8') as f:
    content = f.read()

old = '''<<<<<<< HEAD
        deepseek_api_key: str = "",
        deepseek_model: str = "deepseek-v4-flash-free",
        deepseek_base_url: str = "https://opencode.ai/zen/v1",
=======
        nemotron_api_key: str = "",
        nemotron_model: str = "nemotron-3.5-free",
        nemotron_base_url: str = "https://opencode.ai/zen/v1",
>>>>>>> bb04106 (Troca DeepSeek por Nemotron 3.5 do opencode zen)
    ):

        self.api_key = api_key

        self.model = model or self.DEFAULT_MODEL

        self.timeout_seconds = timeout_seconds

        self.max_retries = max_retries

        self.NEMOTRON_API_KEY = nemotron_api_key

        self.NEMOTRON_MODEL = nemotron_model

        self.NEMOTRON_BASE_URL = nemotron_base_url

        self._client = None'''

new = '''        nemotron_api_key: str = "",
        nemotron_model: str = "nemotron-3.5-free",
        nemotron_base_url: str = "https://opencode.ai/zen/v1",
    ):

        self.api_key = api_key

        self.model = model or self.DEFAULT_MODEL

        self.timeout_seconds = timeout_seconds

        self.max_retries = max_retries

        self.NEMOTRON_API_KEY = nemotron_api_key

        self.NEMOTRON_MODEL = nemotron_model

        self.NEMOTRON_BASE_URL = nemotron_base_url

        self._client = None'''

if "<<<<<<< HEAD" in content:
    content = content.replace(
        "<<<<<<< HEAD\n        deepseek_api_key: str = \"\",\n        deepseek_model: str = \"deepseek-v4-flash-free\",\n        deepseek_base_url: str = \"https://opencode.ai/zen/v1\",\n=======\n        nemotron_api_key: str = \"\",\n        nemotron_model: str = \"nemotron-3.5-free\",\n        nemotron_base_url: str = \"https://opencode.ai/zen/v1\",\n>>>>>>> bb04106 (Troca DeepSeek por Nemotron 3.5 do opencode zen)\n    ):\n\n        self.api_key = api_key\n\n        self.model = model or self.DEFAULT_MODEL\n\n        self.timeout_seconds = timeout_seconds\n\n        self.max_retries = max_retries\n\n        self.NEMOTRON_API_KEY = nemotron_api_key\n\n        self.NEMOTRON_MODEL = nemotron_model\n\n        self.NEMOTRON_BASE_URL = nemotron_base_url\n\n        self._client = None",
        "        nemotron_api_key: str = \"\",\n        nemotron_model: str = \"nemotron-3.5-free\",\n        nemotron_base_url: str = \"https://opencode.ai/zen/v1\",\n    ):\n\n        self.api_key = api_key\n\n        self.model = model or self.DEFAULT_MODEL\n\n        self.timeout_seconds = timeout_seconds\n\n        self.max_retries = max_retries\n\n        self.NEMOTRON_API_KEY = nemotron_api_key\n\n        self.NEMOTRON_MODEL = nemotron_model\n\n        self.NEMOTRON_BASE_URL = nemotron_base_url\n\n        self._client = None"
    )
    with open(r'C:\Users\carlo\Desktop\B3-bot\ai_analyzer.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('ai_analyzer.py resolved')
else:
    print('No conflicts found')