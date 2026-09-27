# =================== AIPass ====================
# Name: test_commons.py
# Description: Integration tests for The Commons social network (posts, comments, votes, rooms, feeds)
# Version: 1.0.0
# Created: 2026-03-07
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/database/db.py and the handlers it drives (notifications, profiles, welcome, search)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the handlers this file drives parse and import
# seedgo: no-test-needed(duplicate) — get_reactions_detailed and get_reaction_summary; test_curation.py pins them
# seedgo: no-test-needed(duplicate) — search_all; test_search.py and test_space_catchup.py pin it
# seedgo: no-test-needed(duplicate) — get_db and DB_PATH resolution; test_lifecycle.py pins db.py's live-path side
# seedgo: no-test-needed(duplicate) — the commands' printed output; test_search.py, test_curation_explore_welcome_ops.py

import functools
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

import pytest

from aipass.commons.apps.handlers.database.db import init_db, close_db
from aipass.commons.apps.handlers.notifications.preferences import (
    get_preference,
    set_preference,
    get_all_preferences,
    should_notify,
    get_watchers,
)
from aipass.commons.apps.handlers.profiles.profile_queries import (
    get_profile,
    update_bio,
    update_status,
    update_role,
    get_activity_stats,
    increment_post_count,
    increment_comment_count,
)
from aipass.commons.apps.handlers.welcome.welcome_handler import (
    create_welcome_post,
    has_been_welcomed,
    get_onboarding_nudge,
    welcome_new_branches,
)
from aipass.commons.apps.handlers.search.search_queries import (
    search_posts,
    search_comments,
    search_all,
    sync_post_to_fts,
    sync_comment_to_fts,
)
from aipass.commons.apps.handlers.search.log_export import export_room_log
from aipass.commons.apps.handlers.curation.reaction_queries import (
    add_reaction,
    remove_reaction,
    get_reactions,
    get_reactions_detailed,
    get_reaction_summary,
)
from aipass.commons.apps.handlers.curation.pin_queries import (
    pin_post,
    unpin_post,
    get_pinned_posts,
    is_pinned,
)


@functools.lru_cache(maxsize=1)
def _get_template_db() -> Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
    path = Path(tmp.name)
    tmp.close()
    conn = init_db(path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    close_db(conn)
    return path


def _fast_db(db_path):
    shutil.copy2(str(_get_template_db()), str(db_path))
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = MEMORY")
    conn.execute("PRAGMA synchronous = OFF")
    return conn


class TestNotificationPreferences(unittest.TestCase):
    """Test notification preference CRUD and should_notify logic."""

    def setup_method(self, _method):
        """Create a fresh test database with agents."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = Path(self.temp_db.name)
        self.temp_db.close()

        self.conn = _fast_db(self.db_path)

        for agent in ["AGENT_A", "AGENT_B", "AGENT_C"]:
            self.conn.execute(
                "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
                (agent, agent.replace("_", " ").title()),
            )
        self.conn.commit()

        self.get_preference = get_preference
        self.set_preference = set_preference
        self.get_all_preferences = get_all_preferences
        self.should_notify = should_notify
        self.get_watchers = get_watchers

    def teardown_method(self, _method):
        """Clean up test database."""
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_set_and_get_preference(self):
        """Test setting and retrieving a notification preference."""
        result = self.set_preference(self.conn, "AGENT_A", "room", "general", "watch")
        self.assertTrue(result)

        level = self.get_preference(self.conn, "AGENT_A", "room", "general")
        self.assertEqual(level, "watch")

    def test_default_preference_is_track(self):
        """Test that no explicit preference returns None (meaning default track)."""
        level = self.get_preference(self.conn, "AGENT_A", "room", "general")
        self.assertIsNone(level)

        result = self.should_notify(self.conn, "AGENT_A", "room", "general", "mention")
        self.assertTrue(result)

        result = self.should_notify(self.conn, "AGENT_A", "room", "general", "new_post")
        self.assertFalse(result)

    def test_mute_blocks_notifications(self):
        """Test that muted targets block all notification types."""
        self.set_preference(self.conn, "AGENT_A", "room", "general", "mute")

        self.assertFalse(self.should_notify(self.conn, "AGENT_A", "room", "general", "mention"))
        self.assertFalse(self.should_notify(self.conn, "AGENT_A", "room", "general", "reply"))
        self.assertFalse(self.should_notify(self.conn, "AGENT_A", "room", "general", "new_post"))
        self.assertFalse(self.should_notify(self.conn, "AGENT_A", "room", "general", "new_comment"))

    def test_watch_enables_all_notifications(self):
        """Test that watched targets enable all notification types."""
        self.set_preference(self.conn, "AGENT_A", "room", "general", "watch")

        self.assertTrue(self.should_notify(self.conn, "AGENT_A", "room", "general", "mention"))
        self.assertTrue(self.should_notify(self.conn, "AGENT_A", "room", "general", "reply"))
        self.assertTrue(self.should_notify(self.conn, "AGENT_A", "room", "general", "new_post"))
        self.assertTrue(self.should_notify(self.conn, "AGENT_A", "room", "general", "new_comment"))

    def test_should_notify_mention_default(self):
        """Test that mentions notify under default (track) behavior."""
        result = self.should_notify(self.conn, "AGENT_B", "room", "general", "mention")
        self.assertTrue(result)

        self.set_preference(self.conn, "AGENT_B", "post", "1", "track")
        result = self.should_notify(self.conn, "AGENT_B", "post", "1", "mention")
        self.assertTrue(result)

        result = self.should_notify(self.conn, "AGENT_B", "post", "1", "new_post")
        self.assertFalse(result)

    def test_should_notify_new_post_watch_only(self):
        """Test that new_post events only notify watchers, not trackers."""
        result = self.should_notify(self.conn, "AGENT_A", "room", "general", "new_post")
        self.assertFalse(result)

        self.set_preference(self.conn, "AGENT_B", "room", "general", "track")
        result = self.should_notify(self.conn, "AGENT_B", "room", "general", "new_post")
        self.assertFalse(result)

        self.set_preference(self.conn, "AGENT_C", "room", "general", "watch")
        result = self.should_notify(self.conn, "AGENT_C", "room", "general", "new_post")
        self.assertTrue(result)

    def test_get_all_preferences(self):
        """Test retrieving all preferences for an agent."""
        self.set_preference(self.conn, "AGENT_A", "room", "general", "watch")
        self.set_preference(self.conn, "AGENT_A", "post", "5", "mute")
        self.set_preference(self.conn, "AGENT_A", "thread", "10", "track")

        prefs = self.get_all_preferences(self.conn, "AGENT_A")
        self.assertEqual(len(prefs), 3)

        types = [p["target_type"] for p in prefs]
        self.assertEqual(types, ["post", "room", "thread"])

    def test_get_watchers(self):
        """Test retrieving all watchers for a target."""
        self.set_preference(self.conn, "AGENT_A", "room", "general", "watch")
        self.set_preference(self.conn, "AGENT_B", "room", "general", "watch")
        self.set_preference(self.conn, "AGENT_C", "room", "general", "track")

        watchers = self.get_watchers(self.conn, "room", "general")
        self.assertEqual(len(watchers), 2)
        self.assertIn("AGENT_A", watchers)
        self.assertIn("AGENT_B", watchers)
        self.assertNotIn("AGENT_C", watchers)

    def test_preference_override(self):
        """Test that setting a preference twice overwrites the first."""
        self.set_preference(self.conn, "AGENT_A", "room", "general", "watch")
        level = self.get_preference(self.conn, "AGENT_A", "room", "general")
        self.assertEqual(level, "watch")

        self.set_preference(self.conn, "AGENT_A", "room", "general", "mute")
        level = self.get_preference(self.conn, "AGENT_A", "room", "general")
        self.assertEqual(level, "mute")

    def test_notification_preferences_table_exists(self):
        """Test that the notification_preferences table is created by init_db."""
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='notification_preferences'"
        ).fetchall()
        self.assertEqual(len(tables), 1)

    def test_notif_prefs_index_exists(self):
        """Test that the notification preferences index is created."""
        indexes = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_notif_prefs_agent'"
        ).fetchall()
        self.assertEqual(len(indexes), 1)


class TestSocialProfiles(unittest.TestCase):
    """Test social profile columns, updates, and activity counters."""

    def setup_method(self, _method):
        """Create a fresh test database with agents."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = Path(self.temp_db.name)
        self.temp_db.close()

        self.conn = _fast_db(self.db_path)

        for agent in ["PROFILE_A", "PROFILE_B"]:
            self.conn.execute(
                "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
                (agent, agent.replace("_", " ").title()),
            )
        self.conn.commit()

        self.get_profile = get_profile
        self.update_bio = update_bio
        self.update_status = update_status
        self.update_role = update_role
        self.get_activity_stats = get_activity_stats
        self.increment_post_count = increment_post_count
        self.increment_comment_count = increment_comment_count

    def teardown_method(self, _method):
        """Clean up test database."""
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_profile_columns_exist(self):
        """Test that bio, status, role, post_count, comment_count columns exist."""
        row = self.conn.execute(
            "SELECT bio, status, role, post_count, comment_count FROM agents WHERE branch_name = ?", ("PROFILE_A",)
        ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["bio"], "")
        self.assertEqual(row["status"], "")
        self.assertEqual(row["role"], "")
        self.assertEqual(row["post_count"], 0)
        self.assertEqual(row["comment_count"], 0)

    def test_update_bio(self):
        """Test updating an agent's bio.

        Mutant: update_bio writes (bio.upper(), branch_name) - the stored bio no longer equals the one given.
        """
        result = self.update_bio(self.conn, "PROFILE_A", "I enforce code quality standards")
        self.assertTrue(result)

        profile = self.get_profile(self.conn, "PROFILE_A")
        assert profile is not None
        assert profile["bio"] == "I enforce code quality standards"

    def test_update_status(self):
        """Test updating an agent's status.

        Mutant: update_status writes (status.upper(), branch_name) - the stored status no longer equals the one given.
        """
        result = self.update_status(self.conn, "PROFILE_A", "Auditing branches")
        self.assertTrue(result)

        profile = self.get_profile(self.conn, "PROFILE_A")
        assert profile is not None
        assert profile["status"] == "Auditing branches"

    def test_update_role(self):
        """Test updating an agent's role.

        Mutant: update_role writes (role.upper(), branch_name) - the stored role no longer equals the one given.
        """
        result = self.update_role(self.conn, "PROFILE_A", "Standards Authority")
        self.assertTrue(result)

        profile = self.get_profile(self.conn, "PROFILE_A")
        assert profile is not None
        assert profile["role"] == "Standards Authority"

    def test_increment_post_count(self):
        """Test incrementing post_count.

        Mutant: SET post_count = 1 instead of post_count + 1 - the second increment stays at 1.
        """
        self.increment_post_count(self.conn, "PROFILE_A")
        self.conn.commit()

        stats = self.get_activity_stats(self.conn, "PROFILE_A")
        assert stats is not None
        assert stats["post_count"] == 1

        self.increment_post_count(self.conn, "PROFILE_A")
        self.conn.commit()

        stats = self.get_activity_stats(self.conn, "PROFILE_A")
        assert stats is not None
        assert stats["post_count"] == 2

    def test_increment_comment_count(self):
        """Test incrementing comment_count.

        Mutant: SET comment_count = 1 instead of comment_count + 1 - four increments stay at 1.
        """
        self.increment_comment_count(self.conn, "PROFILE_A")
        self.conn.commit()

        stats = self.get_activity_stats(self.conn, "PROFILE_A")
        assert stats is not None
        assert stats["comment_count"] == 1

        for _ in range(3):
            self.increment_comment_count(self.conn, "PROFILE_A")
        self.conn.commit()

        stats = self.get_activity_stats(self.conn, "PROFILE_A")
        assert stats is not None
        assert stats["comment_count"] == 4

    def test_get_profile_returns_all_fields(self):
        """Test that get_profile returns all expected profile fields.

        Mutant: get_profile's SELECT drops the role column - the key set no longer matches.
        """
        self.update_bio(self.conn, "PROFILE_B", "Test bio")
        self.update_status(self.conn, "PROFILE_B", "Testing")
        self.update_role(self.conn, "PROFILE_B", "Tester")

        profile = self.get_profile(self.conn, "PROFILE_B")

        self.assertIsNotNone(profile)
        assert profile is not None
        expected_keys = [
            "branch_name",
            "display_name",
            "description",
            "karma",
            "joined_at",
            "last_active",
            "bio",
            "status",
            "role",
            "post_count",
            "comment_count",
        ]
        assert sorted(profile) == sorted(expected_keys)

        self.assertEqual(profile["branch_name"], "PROFILE_B")
        self.assertEqual(profile["bio"], "Test bio")
        self.assertEqual(profile["status"], "Testing")
        self.assertEqual(profile["role"], "Tester")
        self.assertEqual(profile["karma"], 0)
        self.assertEqual(profile["post_count"], 0)
        self.assertEqual(profile["comment_count"], 0)


class TestWelcomeOnboarding(unittest.TestCase):
    """Test welcome posts, duplicate prevention, and onboarding nudges."""

    def setup_method(self, _method):
        """Create a fresh test database with agents."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = Path(self.temp_db.name)
        self.temp_db.close()

        self.conn = _fast_db(self.db_path)

        for agent in ["WELCOME_A", "WELCOME_B", "WELCOME_C"]:
            self.conn.execute(
                "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
                (agent, agent.replace("_", " ").title()),
            )
        self.conn.commit()

        self.create_welcome_post = create_welcome_post
        self.has_been_welcomed = has_been_welcomed
        self.get_onboarding_nudge = get_onboarding_nudge
        self.welcome_new_branches = welcome_new_branches

    def teardown_method(self, _method):
        """Clean up test database."""
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_create_welcome_post(self):
        """Test that a welcome post is created with correct title, author, and type."""
        post_id = self.create_welcome_post(self.conn, "WELCOME_A")

        self.assertIsNotNone(post_id)

        post = self.conn.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()

        self.assertIsNotNone(post)
        self.assertEqual(post["author"], "SYSTEM")
        self.assertEqual(post["title"], "Welcome @WELCOME_A to The Commons!")
        self.assertEqual(post["post_type"], "announcement")
        self.assertEqual(post["room_name"], "general")
        self.assertIn("@WELCOME_A", post["content"])

        mention = self.conn.execute(
            "SELECT * FROM mentions WHERE mentioned_agent = ? AND mentioner_agent = 'SYSTEM'", ("WELCOME_A",)
        ).fetchone()
        self.assertIsNotNone(mention)
        self.assertEqual(mention["post_id"], post_id)

    def test_has_been_welcomed_true(self):
        """Test that has_been_welcomed returns True after creating a welcome post."""
        self.create_welcome_post(self.conn, "WELCOME_A")

        result = self.has_been_welcomed(self.conn, "WELCOME_A")
        self.assertTrue(result)

    def test_has_been_welcomed_false(self):
        """Test that has_been_welcomed returns False for unwelcomed branches."""
        result = self.has_been_welcomed(self.conn, "WELCOME_B")
        self.assertFalse(result)

    def test_no_duplicate_welcome(self):
        """Test that calling create_welcome_post twice doesn't create duplicates."""
        post_id_1 = self.create_welcome_post(self.conn, "WELCOME_A")
        post_id_2 = self.create_welcome_post(self.conn, "WELCOME_A")

        self.assertIsNotNone(post_id_1)
        self.assertIsNone(post_id_2)

        count = self.conn.execute(
            "SELECT COUNT(*) FROM posts WHERE author = 'SYSTEM' AND title LIKE 'Welcome @WELCOME_A%'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_onboarding_nudge_new_user(self):
        """Test that a branch with no posts and no comments gets a nudge.

        Mutant: the new-user message reads "You have not posted yet" - the nudge no longer opens as pinned.
        """
        nudge = self.get_onboarding_nudge(self.conn, "WELCOME_A")

        self.assertIsNotNone(nudge)
        assert nudge is not None
        assert nudge.startswith("You haven't posted yet!")
        self.assertIn("commons post", nudge)

    def test_onboarding_nudge_active_user(self):
        """Test that a branch with posts returns None (no nudge needed)."""
        self.conn.execute("UPDATE agents SET post_count = 3 WHERE branch_name = ?", ("WELCOME_B",))
        self.conn.commit()

        nudge = self.get_onboarding_nudge(self.conn, "WELCOME_B")
        self.assertIsNone(nudge)

    def test_onboarding_nudge_commenter_only(self):
        """Test that a branch with comments but no posts gets a specific nudge.

        Mutant: the new-user branch tests comment_count >= 0 - a commenter gets the new-user nudge instead.
        """
        self.conn.execute("UPDATE agents SET comment_count = 5, post_count = 0 WHERE branch_name = ?", ("WELCOME_C",))
        self.conn.commit()

        nudge = self.get_onboarding_nudge(self.conn, "WELCOME_C")

        self.assertIsNotNone(nudge)
        assert nudge is not None
        assert nudge.startswith("You've been commenting but never posted!")

    def test_welcome_new_branches(self):
        """Test that welcome_new_branches scans and welcomes all unwelcomed branches."""
        self.create_welcome_post(self.conn, "WELCOME_A")

        welcomed = self.welcome_new_branches(self.conn)

        self.assertIn("WELCOME_B", welcomed)
        self.assertIn("WELCOME_C", welcomed)
        self.assertNotIn("WELCOME_A", welcomed)
        self.assertNotIn("SYSTEM", welcomed)

        self.assertTrue(self.has_been_welcomed(self.conn, "WELCOME_A"))
        self.assertTrue(self.has_been_welcomed(self.conn, "WELCOME_B"))
        self.assertTrue(self.has_been_welcomed(self.conn, "WELCOME_C"))


class TestSearchAndLogs(unittest.TestCase):
    """Test FTS5 search and log export."""

    def setup_method(self, _method):
        """Create a fresh test database with agents and sample data."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = Path(self.temp_db.name)
        self.temp_db.close()

        self.conn = _fast_db(self.db_path)

        for agent in ["SEARCH_A", "SEARCH_B", "SEARCH_C"]:
            self.conn.execute(
                "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
                (agent, agent.replace("_", " ").title()),
            )
        self.conn.commit()

        self.search_posts = search_posts
        self.search_comments = search_comments
        self.search_all = search_all
        self.sync_post_to_fts = sync_post_to_fts
        self.sync_comment_to_fts = sync_comment_to_fts
        self.export_room_log = export_room_log

    def teardown_method(self, _method):
        """Clean up test database."""
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def _create_post(self, room, author, title, content):
        """Helper to create a post and sync to FTS."""
        cursor = self.conn.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)", (room, author, title, content)
        )
        post_id = cursor.lastrowid
        assert post_id is not None
        self.conn.commit()
        self.sync_post_to_fts(self.conn, post_id, title, content, author, room)
        self.conn.commit()
        return post_id

    def _create_comment(self, post_id, author, content, parent_id=None):
        """Helper to create a comment and sync to FTS."""
        cursor = self.conn.execute(
            "INSERT INTO comments (post_id, parent_id, author, content) VALUES (?, ?, ?, ?)",
            (post_id, parent_id, author, content),
        )
        comment_id = cursor.lastrowid
        assert comment_id is not None
        self.conn.commit()
        self.sync_comment_to_fts(self.conn, comment_id, content, author)
        self.conn.commit()
        return comment_id

    def test_fts_tables_exist(self):
        """Test that FTS5 virtual tables are created by init_db."""
        tables = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('posts_fts', 'comments_fts')"
        ).fetchall()
        table_names = [t["name"] for t in tables]

        self.assertIn("posts_fts", table_names)
        self.assertIn("comments_fts", table_names)

    def test_search_posts_by_keyword(self):
        """Test searching posts by keyword returns matching results."""
        self._create_post("general", "SEARCH_A", "Hello World", "First post in The Commons!")
        self._create_post("general", "SEARCH_B", "Goodbye World", "Leaving the commons")
        self._create_post("watercooler", "SEARCH_A", "Random Thoughts", "Nothing about greetings here")

        results = self.search_posts(self.conn, "hello")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Hello World")

        results = self.search_posts(self.conn, "world")
        self.assertEqual(len(results), 2)

    def test_search_comments_by_keyword(self):
        """Test searching comments by keyword returns matching results."""
        post_id = self._create_post("general", "SEARCH_A", "Test Post", "A test post")
        self._create_comment(post_id, "SEARCH_B", "Great work on this feature!")
        self._create_comment(post_id, "SEARCH_C", "I agree, excellent implementation")

        results = self.search_comments(self.conn, "feature")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["author"], "SEARCH_B")

    def test_search_filter_by_room(self):
        """Test filtering search results by room."""
        self._create_post("general", "SEARCH_A", "General Update", "Update in general room")
        self._create_post("watercooler", "SEARCH_A", "Watercooler Update", "Update in watercooler room")

        results = self.search_posts(self.conn, "update", room="general")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["room_name"], "general")

        results = self.search_posts(self.conn, "update", room="watercooler")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["room_name"], "watercooler")

    def test_search_filter_by_author(self):
        """Test filtering search results by author."""
        self._create_post("general", "SEARCH_A", "Post by A", "Content from agent A")
        self._create_post("general", "SEARCH_B", "Post by B", "Content from agent B")

        results = self.search_posts(self.conn, "content", author="SEARCH_A")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["author"], "SEARCH_A")

        results = self.search_posts(self.conn, "content", author="SEARCH_B")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["author"], "SEARCH_B")

    def test_sync_post_to_fts(self):
        """Test that syncing a post to FTS makes it searchable.

        Mutant: sync_post_to_fts indexes rowid post_id + 1 - the search no longer finds this post.
        """
        cursor = self.conn.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "SEARCH_A", "Unsynced Post", "This is not yet indexed"),
        )
        post_id = cursor.lastrowid
        assert post_id is not None
        self.conn.commit()

        results = self.search_posts(self.conn, "unsynced")
        self.assertEqual(len(results), 0)

        self.sync_post_to_fts(self.conn, post_id, "Unsynced Post", "This is not yet indexed", "SEARCH_A", "general")
        self.conn.commit()

        results = self.search_posts(self.conn, "unsynced")
        assert [r["id"] for r in results] == [post_id]

    def test_log_export_format(self):
        """Test that log export produces correctly formatted plaintext."""
        post_id = self._create_post("general", "SEARCH_A", "Hello World", "First post in The Commons!")

        comment_id = self._create_comment(post_id, "SEARCH_B", "Great to see activity!")
        self._create_comment(post_id, "SEARCH_C", "Welcome everyone")
        self._create_comment(post_id, "SEARCH_A", "Thanks!", parent_id=comment_id)

        log_text = self.export_room_log(self.conn, "general")

        self.assertIn("=== r/general - The Commons Log ===", log_text)
        self.assertIn("Exported:", log_text)

        self.assertIn("Post #", log_text)
        self.assertIn('"Hello World"', log_text)
        self.assertIn("SEARCH_A", log_text)
        self.assertIn("First post in The Commons!", log_text)

        self.assertIn("SEARCH_B: Great to see activity!", log_text)
        self.assertIn("SEARCH_C: Welcome everyone", log_text)
        self.assertIn("SEARCH_A: Thanks!", log_text)


class TestReactionsAndPins(unittest.TestCase):
    """Test reactions, pins, and trending detection."""

    def setup_method(self, _method):
        """Create a fresh test database with agents, posts, and comments."""
        self.temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        self.db_path = Path(self.temp_db.name)
        self.temp_db.close()

        self.conn = _fast_db(self.db_path)

        for agent in ["REACT_A", "REACT_B", "REACT_C", "AUTHOR_X"]:
            self.conn.execute(
                "INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES (?, ?)",
                (agent, agent.replace("_", " ").title()),
            )

        self.conn.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("general", "AUTHOR_X", "Reactions Test Post", "Content for reactions"),
        )
        self.conn.commit()
        self.post_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        self.conn.execute(
            "INSERT INTO comments (post_id, author, content) VALUES (?, ?, ?)",
            (self.post_id, "AUTHOR_X", "Test comment for reactions"),
        )
        self.conn.commit()
        self.comment_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        self.add_reaction = add_reaction
        self.remove_reaction = remove_reaction
        self.get_reactions = get_reactions
        self.get_reactions_detailed = get_reactions_detailed
        self.get_reaction_summary = get_reaction_summary
        self.pin_post = pin_post
        self.unpin_post = unpin_post
        self.get_pinned_posts = get_pinned_posts
        self.is_pinned = is_pinned

    def teardown_method(self, _method):
        """Clean up test database."""
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def test_reactions_table_exists(self):
        """Test that the reactions table is created by init_db."""
        tables = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='reactions'").fetchall()
        self.assertEqual(len(tables), 1)

    def test_add_reaction_to_post(self):
        """Test adding a reaction to a post."""
        result = self.add_reaction(self.conn, "REACT_A", "thumbsup", post_id=self.post_id)
        self.assertTrue(result)

        row = self.conn.execute(
            "SELECT * FROM reactions WHERE agent_name = ? AND post_id = ? AND reaction = ?",
            ("REACT_A", self.post_id, "thumbsup"),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["agent_name"], "REACT_A")
        self.assertEqual(row["reaction"], "thumbsup")
        self.assertIsNone(row["comment_id"])

    def test_add_reaction_to_comment(self):
        """Test adding a reaction to a comment."""
        result = self.add_reaction(self.conn, "REACT_A", "agree", comment_id=self.comment_id)
        self.assertTrue(result)

        row = self.conn.execute(
            "SELECT * FROM reactions WHERE agent_name = ? AND comment_id = ? AND reaction = ?",
            ("REACT_A", self.comment_id, "agree"),
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["reaction"], "agree")
        self.assertIsNone(row["post_id"])

    def test_no_duplicate_reaction(self):
        """Test that the same agent cannot add the same reaction twice."""
        result1 = self.add_reaction(self.conn, "REACT_A", "thumbsup", post_id=self.post_id)
        self.assertTrue(result1)

        result2 = self.add_reaction(self.conn, "REACT_A", "thumbsup", post_id=self.post_id)
        self.assertFalse(result2)

        count = self.conn.execute(
            "SELECT COUNT(*) FROM reactions WHERE agent_name = ? AND post_id = ? AND reaction = ?",
            ("REACT_A", self.post_id, "thumbsup"),
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_remove_reaction(self):
        """Test removing a reaction."""
        self.add_reaction(self.conn, "REACT_A", "thumbsup", post_id=self.post_id)

        result = self.remove_reaction(self.conn, "REACT_A", "thumbsup", post_id=self.post_id)
        self.assertTrue(result)

        row = self.conn.execute(
            "SELECT * FROM reactions WHERE agent_name = ? AND post_id = ? AND reaction = ?",
            ("REACT_A", self.post_id, "thumbsup"),
        ).fetchone()
        self.assertIsNone(row)

        result2 = self.remove_reaction(self.conn, "REACT_A", "thumbsup", post_id=self.post_id)
        self.assertFalse(result2)

    def test_get_reactions_count(self):
        """Test getting reaction counts for a post."""
        self.add_reaction(self.conn, "REACT_A", "thumbsup", post_id=self.post_id)
        self.add_reaction(self.conn, "REACT_B", "thumbsup", post_id=self.post_id)
        self.add_reaction(self.conn, "REACT_C", "thumbsup", post_id=self.post_id)
        self.add_reaction(self.conn, "REACT_A", "interesting", post_id=self.post_id)
        self.add_reaction(self.conn, "REACT_B", "agree", post_id=self.post_id)
        self.add_reaction(self.conn, "REACT_C", "agree", post_id=self.post_id)

        counts = self.get_reactions(self.conn, post_id=self.post_id)

        self.assertEqual(counts.get("thumbsup"), 3)
        self.assertEqual(counts.get("interesting"), 1)
        self.assertEqual(counts.get("agree"), 2)
        self.assertNotIn("disagree", counts)
        self.assertNotIn("celebrate", counts)
        self.assertNotIn("thinking", counts)

    def test_pin_post(self):
        """Test pinning a post."""
        self.assertFalse(self.is_pinned(self.conn, self.post_id))

        result = self.pin_post(self.conn, self.post_id)
        self.assertTrue(result)
        self.assertTrue(self.is_pinned(self.conn, self.post_id))

        row = self.conn.execute("SELECT pinned FROM posts WHERE id = ?", (self.post_id,)).fetchone()
        self.assertEqual(row["pinned"], 1)

    def test_unpin_post(self):
        """Test unpinning a post."""
        self.pin_post(self.conn, self.post_id)
        self.assertTrue(self.is_pinned(self.conn, self.post_id))

        result = self.unpin_post(self.conn, self.post_id)
        self.assertTrue(result)
        self.assertFalse(self.is_pinned(self.conn, self.post_id))

        row = self.conn.execute("SELECT pinned FROM posts WHERE id = ?", (self.post_id,)).fetchone()
        self.assertEqual(row["pinned"], 0)

    def test_get_pinned_posts(self):
        """Test getting all pinned posts with optional room filter."""
        self.conn.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES (?, ?, ?, ?)",
            ("watercooler", "AUTHOR_X", "Watercooler Pinned", "Content"),
        )
        self.conn.commit()
        wc_post_id = self.conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        self.pin_post(self.conn, self.post_id)
        self.pin_post(self.conn, wc_post_id)

        all_pinned = self.get_pinned_posts(self.conn)
        self.assertEqual(len(all_pinned), 2)

        general_pinned = self.get_pinned_posts(self.conn, room_name="general")
        self.assertEqual(len(general_pinned), 1)
        self.assertEqual(general_pinned[0]["title"], "Reactions Test Post")

        wc_pinned = self.get_pinned_posts(self.conn, room_name="watercooler")
        self.assertEqual(len(wc_pinned), 1)
        self.assertEqual(wc_pinned[0]["title"], "Watercooler Pinned")

    def test_pinned_column_exists(self):
        """Test that the pinned column exists on posts table."""
        row = self.conn.execute("SELECT pinned FROM posts WHERE id = ?", (self.post_id,)).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["pinned"], 0)


# ===========================================================================
# schema.sql as init_db applies it — constraints, indexes, seeded rooms
# ===========================================================================
# Each test opens its own database through init_db, so the subject is this
# branch's schema.sql, not SQLite. Dropping the named clause from schema.sql
# is the bug that reddens each one.


def test_schema_seeds_the_default_rooms(tmp_path: Path) -> None:
    """init_db seeds general and watercooler; drop either seed row and this reddens."""
    conn = init_db(tmp_path / "commons.db")
    room_names = {r["name"] for r in conn.execute("SELECT name FROM rooms").fetchall()}
    close_db(conn)
    assert {"general", "watercooler"} <= room_names


def test_schema_refuses_a_post_to_an_unknown_room(tmp_path: Path) -> None:
    """posts.room_name REFERENCES rooms(name); drop the foreign key and the insert succeeds."""
    conn = init_db(tmp_path / "commons.db")
    conn.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('TEST_AGENT', 'Test Agent')")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute(
            "INSERT INTO posts (room_name, author, title, content) VALUES ('nonexistent', 'TEST_AGENT', 'T', 'c')"
        )
    close_db(conn)


def test_schema_refuses_a_comment_on_an_unknown_post(tmp_path: Path) -> None:
    """comments.post_id REFERENCES posts(id); drop the foreign key and the insert succeeds."""
    conn = init_db(tmp_path / "commons.db")
    conn.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('TEST_AGENT', 'Test Agent')")
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        conn.execute("INSERT INTO comments (post_id, author, content) VALUES (99999, 'TEST_AGENT', 'c')")
    close_db(conn)


def test_schema_refuses_a_vote_direction_other_than_one_or_minus_one(tmp_path: Path) -> None:
    """votes.direction CHECK (direction IN (1, -1)); drop the CHECK and a 5 is stored."""
    conn = init_db(tmp_path / "commons.db")
    conn.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('TEST_AGENT', 'Test Agent')")
    post_id = conn.execute(
        "INSERT INTO posts (room_name, author, title, content) VALUES ('general', 'TEST_AGENT', 'T', 'c')"
    ).lastrowid
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO votes (agent_name, target_id, target_type, direction) VALUES ('TEST_AGENT', ?, 'post', 5)",
            (post_id,),
        )
    close_db(conn)


def test_schema_refuses_an_unknown_post_type(tmp_path: Path) -> None:
    """posts.post_type CHECK lists four types; drop the CHECK and 'invalid_type' is stored."""
    conn = init_db(tmp_path / "commons.db")
    conn.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('TEST_AGENT', 'Test Agent')")
    with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
        conn.execute(
            "INSERT INTO posts (room_name, author, title, content, post_type)"
            " VALUES ('general', 'TEST_AGENT', 'T', 'c', 'invalid_type')"
        )
    close_db(conn)


def test_schema_refuses_a_second_vote_by_one_agent_on_one_target(tmp_path: Path) -> None:
    """votes UNIQUE (agent_name, target_id, target_type); drop it and a second vote is stored."""
    conn = init_db(tmp_path / "commons.db")
    conn.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('TEST_AGENT', 'Test Agent')")
    post_id = conn.execute(
        "INSERT INTO posts (room_name, author, title, content) VALUES ('general', 'TEST_AGENT', 'T', 'c')"
    ).lastrowid
    vote = "INSERT INTO votes (agent_name, target_id, target_type, direction) VALUES ('TEST_AGENT', ?, 'post', ?)"
    conn.execute(vote, (post_id, 1))
    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        conn.execute(vote, (post_id, -1))
    close_db(conn)


def test_schema_creates_the_lookup_indexes(tmp_path: Path) -> None:
    """schema.sql creates four lookup indexes; drop any CREATE INDEX and this reddens."""
    conn = init_db(tmp_path / "commons.db")
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND sql IS NOT NULL").fetchall()
    close_db(conn)
    assert {"idx_posts_room", "idx_posts_author", "idx_comments_post", "idx_votes_target"} <= {r["name"] for r in rows}


def test_schema_stores_each_of_the_four_post_types(tmp_path: Path) -> None:
    """posts.post_type CHECK accepts discussion, review, question, announcement; drop one and its insert is refused.

    Mutant: init_db applies schema.sql with 'review' dropped from the CHECK - the review insert raises IntegrityError.
    """
    conn = init_db(tmp_path / "commons.db")
    conn.execute("INSERT OR IGNORE INTO agents (branch_name, display_name) VALUES ('TEST_AGENT', 'Test Agent')")
    four = ["discussion", "review", "question", "announcement"]
    for post_type in four:
        conn.execute(
            "INSERT INTO posts (room_name, author, title, content, post_type)"
            " VALUES ('general', 'TEST_AGENT', ?, 'c', ?)",
            (post_type, post_type),
        )
    stored = [r["post_type"] for r in conn.execute("SELECT post_type FROM posts ORDER BY id").fetchall()]
    close_db(conn)
    assert stored == four
