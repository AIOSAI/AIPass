# =================== AIPass ====================
# Name: runner_handler.py
# Description: Skill execution handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-03-08
# =============================================

"""
Skill Execution Handler

Contains the core logic for executing skills: calling handler.run()
for handler-based skills, and assembling output for markdown-only skills.

Purpose:
    Implementation logic for skill execution, separated from
    orchestration layer to satisfy thin-module standard.
"""

from skills.apps.handlers.json import json_handler


def run_handler(handler, name, action, args, config):
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
        json_handler.log_operation("handler_executed", {
            "name": name,
            "action": action,
            "success": True,
        })
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


def run_markdown(name, metadata, body):
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
