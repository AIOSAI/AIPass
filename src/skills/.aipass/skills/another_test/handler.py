"""
another_test skill handler

Called by: drone @skills run another_test <action> [args]
"""


def run(action, args=None, config=None):
    """Execute a skill action.

    Args:
        action: What to do
        args: Dict of action arguments
        config: Dict of resolved config values

    Returns:
        {"success": bool, "output": str, "error": str|None}
    """
    args = args or {}
    config = config or {}

    if action == "example":
        return {"success": True, "output": "It works!", "error": None}

    return {"success": False, "output": "", "error": f"Unknown action: {action}"}


def get_actions():
    """List available actions for this skill."""
    return ["example"]
