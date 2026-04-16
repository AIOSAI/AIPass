"""
Google API Domain

Handlers for Google service authentication, credential management,
and service object factories. Provides authenticated clients for
Google APIs (Drive, Calendar, etc.) to consuming branches.
"""

__version__ = "1.0.0"

from . import auth as auth
from . import service_factory as service_factory
from . import retry as retry
