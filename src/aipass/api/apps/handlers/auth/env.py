# =================== AIPass ====================
# Name: env.py
# Description: .env file operations
# Version: 0.2.0
# Created: 2025-11-16
# Modified: 2026-10-17
# =============================================

""".env File Handler"""

import os
from pathlib import Path

from typing import Optional

from aipass.prax import logger

from aipass.api.apps.handlers.json import json_handler


def create_env_template(provider: str = "openrouter", target_path: Optional[Path] = None) -> bool:
    """Create .env template file with default placeholders."""
    env_path = target_path or (Path.home() / ".secrets" / "aipass" / ".env")

    if env_path.exists():
        logger.info(f".env file already exists at {env_path}")
        return True

    if provider.lower() == "openrouter":
        env_template = """# AIPass API Keys
# Add your API keys here

# OpenRouter API Key (recommended - access to 323+ models)
OPENROUTER_API_KEY=sk-or-v1-your-key-here

# Backup OpenAI API Key (if needed)
OPENAI_API_KEY=sk-your-openai-key-here

# Other provider keys can be added as needed
"""
    else:
        env_template = f"""# AIPass API Keys
# Add your API keys here

# {provider.upper()} API Key
{provider.upper()}_API_KEY=your-key-here

# Other provider keys can be added as needed
"""

    try:
        env_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(env_path.parent, 0o700)

        with open(env_path, "w", encoding="utf-8") as f:
            f.write(env_template)

        os.chmod(env_path, 0o600)

        logger.info(f"Created .env template at {env_path}")
        json_handler.log_operation("env_template_created", {"path": str(env_path), "provider": provider})
        return True

    except Exception as e:
        logger.error(f"Failed to create .env template: {e}")
        return False
