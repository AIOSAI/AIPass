# =================== AIPass ====================
# Name: provider.py
# Description: Provider Configuration Handler
# Version: 2.0.1
# Created: 2025-11-16
# Modified: 2026-10-24
# =============================================

"""Provider Configuration Handler"""

# No default_model: callers name their own model from their branch config.
PROVIDER_DEFAULTS = {
    "openrouter": {
        "api_key": "",
        "base_url": "https://openrouter.ai/api/v1",
        "temperature": 0.7,
        "timeout_seconds": 30,
    },
    "openai": {"api_key": "", "base_url": "https://api.openai.com/v1", "temperature": 0.7, "timeout_seconds": 30},
}
