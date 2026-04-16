"""
User Handlers - User Configuration and Management

Handles user information retrieval for AI_Mail system.
"""

# load.py moved to apps/.archive/users_load(disabled).py
# config_generator.py moved to apps/.archive/config_generator(disabled).py

from .user import get_current_user, get_user_by_email, get_all_users

__all__ = [
    "get_current_user",
    "get_user_by_email",
    "get_all_users",
]
