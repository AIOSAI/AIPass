# =================== AIPass ====================
# Name: runner_handler.py
# Description: Skill execution handler
# Version: 1.0.0
# Created: 2026-03-08
# Modified: 2026-10-17
# =============================================

"""
Skill Execution Handler
"""

from aipass.prax import logger
from aipass.skills.apps.handlers.json import json_handler


def run_handler(handler, name, action, args, config):
    """Run a skill's handler module."""
    if action is None:
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
                logger.error(f"Failed to list actions for {name}: {exc}")
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
        json_handler.log_operation(
            "handler_executed",
            {
                "name": name,
                "action": action,
                "success": True,
            },
        )
        if isinstance(result, dict):
            return {
                "success": result.get("success", False),
                "output": result.get("output", ""),
                "error": result.get("error"),
            }
        return {
            "success": True,
            "output": str(result),
            "error": None,
        }
    except Exception as exc:
        logger.error(f"Skill {name} action '{action}' failed: {exc}")
        return {
            "success": False,
            "output": "",
            "error": f"Skill {name} action '{action}' failed: {exc}",
        }


def run_markdown(name, metadata, body):
    """Run a markdown-only skill by returning its body content."""
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
