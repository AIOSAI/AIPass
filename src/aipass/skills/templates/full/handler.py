"""
{{SKILL_NAME}} — Full 3-layer skill handler.

Scaffolded by: drone @skills create {{SKILL_NAME}} --full
"""


def run(action, args=None, config=None):
    """
    Execute the skill.

    Args:
        action: The action to perform
        args: Dict of action arguments (key=value pairs; positionals as arg0, arg1, ...)
        config: Dict of resolved config values

    Returns:
        dict with keys: success (bool), output (str), error (str|None)
    """
    return {
        "success": True,
        "output": f"{{SKILL_NAME}} executed action: {action}",
        "error": None,
    }
