"""Files arriving over Telegram: download, classify, prompt, clean up.

Pulls an attachment into a temp directory under a sanitised name, decides
whether it is readable text or opaque binary, and builds the prompt the bot
hands onward. Bounded on purpose - a size ceiling, a text-content ceiling
and an explicit extension set - because the sender chooses the file and this
branch chooses what it is willing to read.
"""

import uuid
from pathlib import Path

from aipass.prax import logger


# Constants
TEMP_DIR = Path("/tmp/telegram_uploads")
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
TEXT_CONTENT_LIMIT = 50000

# Text file extensions that can be read as UTF-8
SUPPORTED_TEXT_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".php",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".swift",
    ".kt",
    ".sh",
    ".bash",
    ".zsh",
    ".sql",
    ".html",
    ".css",
    ".scss",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".toml",
    ".ini",
    ".cfg",
    ".md",
    ".txt",
    ".rst",
    ".log",
    ".csv",
    ".env",
    ".gitignore",
    ".dockerfile",
}

# Image file extensions
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg"}

# Map file extensions to language names for code blocks
LANGUAGE_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".java": "java",
    ".go": "go",
    ".rs": "rust",
    ".rb": "ruby",
    ".php": "php",
    ".c": "c",
    ".cpp": "cpp",
    ".h": "c",
    ".cs": "csharp",
    ".swift": "swift",
    ".kt": "kotlin",
    ".sh": "bash",
    ".bash": "bash",
    ".sql": "sql",
    ".html": "html",
    ".css": "css",
    ".json": "json",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".xml": "xml",
    ".toml": "toml",
    ".md": "markdown",
}


def _sanitize_filename(raw_filename: str) -> str:
    """
    Sanitize a filename by removing path separators and dangerous characters.

    Args:
        raw_filename: The original filename to sanitize

    Returns:
        A safe filename string
    """
    safe_name = Path(raw_filename).name
    safe_name = "".join(c if c.isalnum() or c in ".-_" else "_" for c in safe_name)
    return safe_name or str(uuid.uuid4())


async def download_telegram_file(file_obj, filename: str | None = None) -> Path:
    """
    Download a Telegram file to the temp directory.

    Args:
        file_obj: Telegram File object (from get_file())
        filename: Optional original filename

    Returns:
        Path to the downloaded file

    Raises:
        ValueError: If file exceeds MAX_FILE_SIZE
    """
    if file_obj.file_size and file_obj.file_size > MAX_FILE_SIZE:
        raise ValueError(f"File too large: {file_obj.file_size} bytes (max {MAX_FILE_SIZE // (1024 * 1024)}MB)")

    TEMP_DIR.mkdir(parents=True, exist_ok=True)

    if filename:
        safe_name = _sanitize_filename(filename)
    else:
        ext = ""
        if file_obj.file_path:
            ext = Path(file_obj.file_path).suffix
        safe_name = f"{uuid.uuid4()}{ext}"

    dest = TEMP_DIR / safe_name
    await file_obj.download_to_drive(dest)
    logger.info("Downloaded file to %s (%s bytes)", dest, file_obj.file_size)
    return dest


def detect_file_type(file_path: Path) -> str:
    """
    Detect the type of a file based on extension and content.

    Args:
        file_path: Path to the file

    Returns:
        One of: 'text', 'image', 'pdf', 'binary'
    """
    suffix = file_path.suffix.lower()

    if suffix in SUPPORTED_TEXT_EXTENSIONS:
        return "text"

    if suffix in IMAGE_EXTENSIONS:
        return "image"

    if suffix == ".pdf":
        return "pdf"

    # Unknown extension - try reading as UTF-8
    try:
        with open(file_path, "rb") as f:
            sample = f.read(1024)
        sample.decode("utf-8")
        return "text"
    except (UnicodeDecodeError, OSError):
        return "binary"


def build_file_prompt(file_path: Path, file_type: str, caption: str | None = None, sender_name: str = "User") -> str:
    """
    Build a Claude prompt that includes file content.

    Args:
        file_path: Path to the downloaded file
        file_type: One of 'text', 'image', 'pdf', 'binary'
        caption: Optional caption from the Telegram message
        sender_name: Name of the sender

    Returns:
        Formatted prompt string for Claude
    """
    FILE_NAME = file_path.name

    if file_type == "text":
        try:
            FILE_CONTENT = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            FILE_CONTENT = "[Error reading file]"

        if len(FILE_CONTENT) > TEXT_CONTENT_LIMIT:
            FILE_CONTENT = FILE_CONTENT[:TEXT_CONTENT_LIMIT] + "\n[...truncated]"

        FILE_SUFFIX = file_path.suffix.lower()
        FILE_LANGUAGE = LANGUAGE_MAP.get(FILE_SUFFIX, "")

        PROMPT_CAPTION = caption or "Review this file"
        return (
            f"{sender_name} via Telegram: {PROMPT_CAPTION}\n\n"
            f"File: {FILE_NAME}\n\n"
            f"```{FILE_LANGUAGE}\n{FILE_CONTENT}\n```"
        )

    elif file_type == "image":
        PROMPT_CAPTION = caption or "What do you see in this image?"
        return (
            f"{sender_name} via Telegram: {PROMPT_CAPTION}\n\n"
            f"[Image attached at: {file_path}]\n"
            f"Please use the Read tool to view the image file at the path above."
        )

    elif file_type == "pdf":
        PROMPT_CAPTION = caption or "Review this document"
        return (
            f"{sender_name} via Telegram: {PROMPT_CAPTION}\n\n"
            f"[PDF document at: {file_path}]\n"
            f"Please use the Read tool to view the PDF file at the path above."
        )

    else:  # binary
        try:
            FILE_SIZE = file_path.stat().st_size
        except OSError:
            FILE_SIZE = 0
        PROMPT_CAPTION = caption or "I sent a file"
        return (
            f"{sender_name} via Telegram: {PROMPT_CAPTION}\n\n"
            f"[File at: {file_path}] (binary, {FILE_SIZE} bytes)\n"
            f"Note: This is a binary file that may not be directly readable."
        )


def cleanup_file(file_path: Path) -> None:
    """
    Remove a temporary file.

    Args:
        file_path: Path to the file to clean up
    """
    file_path.unlink(missing_ok=True)
    logger.info("Cleaned up temp file: %s", file_path)
