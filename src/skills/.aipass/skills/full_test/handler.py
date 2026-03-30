"""
full_test — Full 3-layer skill handler.

Scaffolded by: drone @skills create full_test --full
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
        "output": f"full_test executed action: {action}",
        "error": None,
    }
