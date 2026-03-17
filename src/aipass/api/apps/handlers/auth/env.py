# =================== AIPass ====================
# Name: env.py
# Description: .env file operations
# Version: 0.2.0
# Created: 2025-11-16
# Modified: 2025-11-16
# =============================================

"""
.env File Handler

Manages .env file reading, creation, and parsing.
Searches multiple paths, creates templates, handles env variables.

Functions:
    read_env_file() - Read environment variable from .env files (multi-path search)
    read_env_file_dict() - Read all variables from .env file as dictionary
    create_env_template() - Create .env template for provider
    validate_env_exists() - Check if .env file exists at any search path
"""

# Infrastructure
from pathlib import Path
import sys

# Standard library
from typing import Optional, Dict, List

# Logging
from aipass.prax import logger

# JSON handler
from aipass.api.apps.handlers.json import json_handler


# ==============================================
# CONSTANTS
# ==============================================

# Default .env search paths (in order of priority)
# Navigate: env.py -> auth/ -> handlers/ -> apps/ -> api/
API_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_ENV_PATHS = [
    Path.home() / ".secrets" / "aipass" / ".env",  # ~/.secrets/aipass/.env (cross-platform standard)
    API_ROOT / ".env",                    # <api_root>/.env
    Path.cwd() / ".env",                  # <cwd>/.env
]


# ==============================================
# ENV FILE READING
# ==============================================

def read_env_file(env_var: str, search_paths: Optional[List[Path]] = None) -> Optional[str]:
    """
    Read environment variable from .env files with multi-path search.

    Searches multiple .env file locations in order:
    1. <api_root>/.env (package-relative)
    2. <cwd>/.env (current working directory)

    Args:
        env_var: Environment variable name to read (e.g., 'OPENROUTER_API_KEY')
        search_paths: Optional custom search paths (defaults to DEFAULT_ENV_PATHS)

    Returns:
        str: Variable value if found, None otherwise

    Example:
        >>> api_key = read_env_file('OPENROUTER_API_KEY')
        >>> if api_key:
        ...     print(f"Found key: {api_key[:20]}...")
    """
    paths = search_paths or DEFAULT_ENV_PATHS

    for env_file in paths:
        if not env_file.exists():
            continue

        try:
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Skip empty lines and comments
                    if not line or line.startswith('#'):
                        continue
                    # Parse key=value
                    if '=' in line:
                        key, value = line.split('=', 1)
                        if key.strip() == env_var:
                            # Found env_var in env_file
                            json_handler.log_operation("env_loaded", {"variable": env_var, "source": str(env_file)})
                            return value.strip()
        except Exception as e:
            # Error reading env_file
            continue

    # Variable not found in any .env file
    return None


def read_env_file_dict(env_path: Path) -> Dict[str, str]:
    """
    Read all environment variables from a .env file as dictionary.

    Args:
        env_path: Path to specific .env file to read

    Returns:
        dict: Dictionary of key-value pairs from .env file

    Example:
        >>> env_vars = read_env_file_dict(Path('api/.env'))
        >>> print(env_vars.get('OPENROUTER_API_KEY'))
    """
    env_dict = {}

    if not env_path.exists():
        # .env file not found
        return env_dict

    try:
        with open(env_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Parse key=value
                if '=' in line:
                    key, value = line.split('=', 1)
                    env_dict[key.strip()] = value.strip()

        # Read variables from env_path
        return env_dict

    except Exception as e:
        # Error reading env_path
        return env_dict


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
        target_path: Optional custom path (defaults to api/.env)

    Returns:
        bool: True if template created successfully, False otherwise

    Example:
        >>> if create_env_template('openrouter'):
        ...     print("Template created at <api_root>/.env")
    """
    # Default to api/.env
    env_path = target_path or (API_ROOT / ".env")

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
        # Ensure parent directory exists
        env_path.parent.mkdir(parents=True, exist_ok=True)

        # Write template
        with open(env_path, 'w', encoding='utf-8') as f:
            f.write(env_template)

        # Created .env template
        logger.info(f"Created .env template at {env_path}")
        return True

    except Exception as e:
        # Failed to create .env template
        logger.error(f"Failed to create .env template: {e}")
        return False


def create_custom_env_template(variables: Dict[str, str], target_path: Path,
                               header: Optional[str] = None) -> bool:
    """
    Create custom .env template with specific variables.

    Args:
        variables: Dictionary of variable names to placeholder values
        target_path: Path where .env file should be created
        header: Optional custom header comment

    Returns:
        bool: True if successful

    Example:
        >>> vars = {
        ...     'DATABASE_URL': 'postgresql://localhost/mydb',
        ...     'SECRET_KEY': 'your-secret-key-here'
        ... }
        >>> create_custom_env_template(vars, Path('/path/to/.env'))
    """
    # Don't overwrite existing file
    if target_path.exists():
        # .env file already exists
        return True

    try:
        # Ensure parent directory exists
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Build template content
        content_lines = []

        # Add header
        if header:
            content_lines.append(f"# {header}")
        else:
            content_lines.append("# Environment Variables")
        content_lines.append("")

        # Add variables
        for key, value in variables.items():
            content_lines.append(f"{key}={value}")

        content = "\n".join(content_lines) + "\n"

        # Write file
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(content)

        # Created custom .env template
        logger.info(f"Created custom .env template at {target_path}")
        return True

    except Exception as e:
        # Failed to create custom .env template
        logger.error(f"Failed to create custom .env template: {e}")
        return False


# ==============================================
# VALIDATION
# ==============================================

def validate_env_exists(search_paths: Optional[List[Path]] = None) -> Optional[Path]:
    """
    Check if .env file exists at any search path.

    Args:
        search_paths: Optional custom search paths (defaults to DEFAULT_ENV_PATHS)

    Returns:
        Path: First found .env file path, or None if none exist

    Example:
        >>> env_path = validate_env_exists()
        >>> if env_path:
        ...     print(f"Found .env at {env_path}")
    """
    paths = search_paths or DEFAULT_ENV_PATHS

    for env_path in paths:
        if env_path.exists():
            # Found .env file
            return env_path

    # No .env file found in search paths
    return None


def get_env_search_paths() -> List[Path]:
    """
    Get list of default .env search paths.

    Returns:
        list: List of Path objects for .env search locations

    Example:
        >>> paths = get_env_search_paths()
        >>> for p in paths:
        ...     print(p)
    """
    return DEFAULT_ENV_PATHS.copy()
