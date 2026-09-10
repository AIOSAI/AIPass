# =================== AIPass ====================
# Name: __init__.py
# Description: Release-notify handler package — manager discovery, body, delivery
# Version: 1.0.0
# Created: 2026-09-09
# Modified: 2026-09-09
# =============================================

"""Release-notify handlers — private implementation for the release_notify module.

Three files, one job each: ``managers`` finds who to tell, ``compose`` writes
what they are told, ``deliver`` sends it and remembers that it did.
"""
