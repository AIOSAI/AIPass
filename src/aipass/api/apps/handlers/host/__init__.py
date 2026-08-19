# =================== AIPass ====================
# Name: __init__.py
# Description: Host API handler package — server, auth and config for the phone lane
# Version: 1.0.0
# Created: 2026-08-14
# Modified: 2026-08-14
# =============================================

"""
Host API handlers (FPLAN-0411).

The Stage 0 host API serves the BAUD phone face over a private network boundary.
This package holds the plumbing only — transport, auth, config. Per FPLAN-0411's
D0 line, no handler here decides what an agent's state MEANS; reads pass another
branch's data through and verbs call another branch's function.

Modules:
    config  - Server config, bind-address validation
    tokens  - Bearer token store: issue, verify, revoke
    server  - FastAPI app factory and auth dependency
"""
