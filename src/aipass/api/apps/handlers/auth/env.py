# =================== AIPass ====================
# Name: env.py
# Description: .env file operations
# Version: 0.2.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
.env File Handler

Manages .env file creation for API credential setup.

Functions:
    create_env_template() - Create .env template for provider
"""

# Infrastructure
import os
from pathlib import Path

# Standard library
from typing import Optional

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler


# ==============================================
# ENV FILE CREATION
# ==============================================


def create_env_template(provider: str = "openrouter", target_path: Optional[Path] = None) -> bool:
    """
    Create .env template file with default placeholders.

    Creates a template .env file with commented instructions and
    placeholder values for API keys. Will not overwrite existing files.

    Args:
        provider: API provider name (default: 'openrouter')
        target_path: Optional custom path (defaults to ~/.secrets/aipass/.env)

    Returns:
        bool: True if template created successfully, False otherwise

    Example:
        >>> if create_env_template('openrouter'):
        ...     print("Template created at ~/.secrets/aipass/.env")
    """
    # Default to ~/.secrets/aipass/.env (cross-platform standard)
    env_path = target_path or (Path.home() / ".secrets" / "aipass" / ".env")

    # Don't overwrite existing file
    if env_path.exists():
        # .env file already exists
        logger.info(f".env file already exists at {env_path}")
        return True

    # Template content based on provider
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
        # Generic template
        env_template = f"""# AIPass API Keys
# Add your API keys here

# {provider.upper()} API Key
{provider.upper()}_API_KEY=your-key-here

# Other provider keys can be added as needed
"""

    try:
        # Ensure parent directory exists with restricted permissions (owner-only)
        env_path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(env_path.parent, 0o700)

        # Write template
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(env_template)

        # Restrict file permissions to owner-read/write only
        os.chmod(env_path, 0o600)

        # Created .env template
        logger.info(f"Created .env template at {env_path}")
        json_handler.log_operation("env_template_created", {"path": str(env_path), "provider": provider})
        return True

    except Exception as e:
        # Failed to create .env template
        logger.error(f"Failed to create .env template: {e}")
        return False
