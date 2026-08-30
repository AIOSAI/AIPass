# =================== AIPass ====================
# Name: __init__.py
# Description: pytest execution pack for the audit-tests lane
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""The pytest execution pack. An ADAPTER pack, not a checker pack.

Declared `kind: execution` in pack.json and it defines no `check_module` or
`check_branch` anywhere, so the audit's file-walk engine cannot see it. Both
statements are enforced: the manifest by the verb, the shape by discovery.
"""
