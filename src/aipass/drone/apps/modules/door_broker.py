# =================== AIPass ====================
# Name: door_broker.py
# Description: Door: drone's identified broker socket and daemon, for ai_mail's dispatch monitor (DPLAN-0404)
# Version: 1.0.0
# Created: 2026-10-07
# Modified: 2026-10-07
# =============================================

"""Door for apps/handlers/broker/client.py and apps/handlers/broker/daemon.py."""

from aipass.drone.apps.handlers.broker.client import create_identified_connection
from aipass.drone.apps.handlers.broker.daemon import BrokerDaemon

__all__ = ["create_identified_connection", "BrokerDaemon"]
