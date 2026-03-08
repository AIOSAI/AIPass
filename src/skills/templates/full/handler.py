"""
{{SKILL_NAME}} — Full 3-layer skill handler.

Scaffolded by: drone @skills create {{SKILL_NAME}} --full
"""


def run(action: str, args: list, config: dict) -> dict:
    """
    Execute the skill.

    Args:
        action: The action to perform
        args: Command arguments
        config: Skill configuration from SKILL.md

    Returns:
        dict with keys: success (bool), output (str), error (str|None)
    """
    return {
        "success": True,
        "output": f"{{SKILL_NAME}} executed action: {action}",
        "error": None,
    }
