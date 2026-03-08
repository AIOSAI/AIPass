# ===================AIPASS====================
# META DATA HEADER
# Name: runner.py - Execute skills
# Date: 2026-03-07
# Version: 1.0.0
# Category: skills/apps/modules
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-03-07): Initial implementation
#
# CODE STANDARDS:
#   - Module layer: orchestration (can print)
#   - Runs skill handlers or displays markdown instructions
# =============================================

"""Skill runner module.

Executes a skill: if it has a handler, calls handler.run();
if no handler, prints the SKILL.md body for the LLM to read.
"""

from skills.apps.modules.loader import load_skill


def run_skill(name, action=None, args=None, config=None):
    """Execute a skill by name.

    Args:
        name: The skill name to run.
        action: The action to perform (required for handler-based skills).
        args: Dict of action arguments.
        config: Dict of resolved config values.

    Returns:
        dict: {"success": bool, "output": str, "error": str|None}
    """
    args = args or {}
    config = config or {}

    # Load the skill
    loaded = load_skill(name)
    if not loaded["success"]:
        return {
            "success": False,
            "output": "",
            "error": loaded["error"],
        }

    handler = loaded["handler"]
    metadata = loaded["metadata"]
    body = loaded["body"]

    # If skill has a handler, call it
    if handler is not None:
        return _run_handler(handler, name, action, args, config)

    # No handler: print the SKILL.md body (LLM reads instructions)
    return _run_markdown(name, metadata, body)


def _run_handler(handler, name, action, args, config):
    """Run a skill's handler module.

    Args:
        handler: The imported handler module.
        name: Skill name (for error messages).
        action: Action to perform.
        args: Dict of action arguments.
        config: Dict of config values.

    Returns:
        dict: {"success": bool, "output": str, "error": str|None}
    """
    if action is None:
        # List available actions if no action specified
        if hasattr(handler, "get_actions"):
            try:
                actions = handler.get_actions()
                action_list = ", ".join(actions)
                return {
                    "success": True,
                    "output": f"Available actions for {name}: {action_list}",
                    "error": None,
                }
            except Exception as exc:
                return {
                    "success": False,
                    "output": "",
                    "error": f"Failed to list actions for {name}: {exc}",
                }
        return {
            "success": False,
            "output": "",
            "error": f"No action specified for {name}. Provide an action to run.",
        }

    if not hasattr(handler, "run"):
        return {
            "success": False,
            "output": "",
            "error": f"Skill {name} handler has no run() function.",
        }

    try:
        result = handler.run(action, args=args, config=config)
        if isinstance(result, dict):
            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error"),
            }
        # If handler returns a non-dict, wrap it
        return {
            "success": True,
            "output": str(result),
            "error": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "output": "",
            "error": f"Skill {name} action '{action}' failed: {exc}",
        }


def _run_markdown(name, metadata, body):
    """Run a markdown-only skill by returning its body content.

    Args:
        name: Skill name.
        metadata: Skill metadata dict.
        body: Markdown body text.

    Returns:
        dict: {"success": bool, "output": str, "error": str|None}
    """
    if not body:
        return {
            "success": True,
            "output": f"Skill '{name}' has no instructions body.",
            "error": None,
        }

    description = metadata.get("description", "")
    header = f"=== Skill: {name} ==="
    if description:
        header += f"\n{description}"
    header += "\n"

    return {
        "success": True,
        "output": f"{header}\n{body}",
        "error": None,
    }
