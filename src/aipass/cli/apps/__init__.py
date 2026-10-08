# ===================AIPASS====================
# META DATA HEADER
# Name: apps/__init__.py
# Date: 2025-11-15
# Version: 1.1.0
# Category: cli/apps
#
# CHANGELOG (Max 5 entries):
#   - v1.1.0 (2026-10-08): the handlers import removed - it made this
#       package the fence's first frame every time (DPLAN-0404)
#   - v1.0.0 (2025-11-15): Initial implementation - Public API
# =============================================

# AIPASS apps package. Imports nothing: handlers are fenced
# (apps/handlers/__init__.py); other branches reach this one through
# aipass.cli.apps.modules.
