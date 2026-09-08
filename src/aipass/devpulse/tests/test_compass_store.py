# =================== AIPass ====================
# Name: test_compass_store.py
# Description: Tests for the compass SQLite/FTS5 storage core
# Version: 1.0.0
# Created: 2026-06-16
# Modified: 2026-06-16
# =============================================

"""Tests for compass storage core — add/query round-trip, rating filter,
stats, rate, archive, review, and FTS5 BM25 ranking.

Every test uses a tmp_path DB via the ``db_path=`` kwarg — never the real
branch-root compass.db.
"""

import sqlite3

import pytest

from aipass.devpulse.apps.handlers import compass
from aipass.devpulse.apps.handlers.compass import store  # internal probe access only


@pytest.fixture
def db(tmp_path):
    """Return a temp compass DB path (file created lazily on first use)."""
    return tmp_path / "compass.db"


class TestFts5Available:
    """FTS5 must be present for compass to function at all."""

    def test_fts5_compiled_in(self):
        """The FTS5 probe used by _connect succeeds on this interpreter."""
        conn = sqlite3.connect(":memory:")
        try:
            store._verify_fts5(conn)  # should not raise
        finally:
            conn.close()


class TestAddQueryRoundTrip:
    """add → query round-trip: the decision is found and its rating returned."""

    def test_add_returns_id(self, db):
        """add_decision returns a positive integer id."""
        new_id = compass.add_decision(
            "Choosing a storage backend",
            "Use SQLite with FTS5",
            "good",
            db_path=db,
        )
        assert isinstance(new_id, int)
        assert new_id > 0

    def test_query_finds_added_decision_with_rating(self, db):
        """A keyword query finds the added decision and returns its rating + fields."""
        compass.add_decision(
            "Choosing a storage backend for compass",
            "Use SQLite with FTS5 instead of ChromaDB",
            "good",
            note="Lighter, no heavy deps",
            tags="storage,sqlite",
            db_path=db,
        )
        results = compass.query_decisions("sqlite", db_path=db)
        assert len(results) == 1
        hit = results[0]
        assert hit["rating"] == "good"
        assert "SQLite" in hit["decision"]
        assert hit["context"].startswith("Choosing a storage backend")
        # Useful fields are present.
        for field in ("id", "created", "note", "tags", "source", "status", "times_surfaced"):
            assert field in hit

    def test_query_matches_on_tags_and_note(self, db):
        """FTS search matches terms that only appear in the note or tags columns."""
        compass.add_decision(
            "Picking a search ranking",
            "BM25 ranking",
            "interesting",
            note="relevance ordering matters",
            tags="ranking,fts5",
            db_path=db,
        )
        # 'relevance' only appears in the note; 'ranking' in tags + context.
        assert len(compass.query_decisions("relevance", db_path=db)) == 1
        assert len(compass.query_decisions("ranking", db_path=db)) == 1

    def test_created_date_is_stamped(self, db):
        """add_decision stamps the supplied created date."""
        compass.add_decision("ctx", "dec", "good", created="2026-06-16", db_path=db)
        hit = compass.query_decisions("ctx", db_path=db)[0]
        assert hit["created"] == "2026-06-16"

    def test_query_increments_times_surfaced(self, db):
        """Each query increments times_surfaced for the returned rows."""
        compass.add_decision("surfacing test context", "a decision", "good", db_path=db)
        first = compass.query_decisions("surfacing", db_path=db)[0]
        assert first["times_surfaced"] == 1
        second = compass.query_decisions("surfacing", db_path=db)[0]
        assert second["times_surfaced"] == 2


class TestRatingFilter:
    """query rating filter returns only matching-rated rows."""

    def test_rating_filter_returns_only_bad(self, db):
        """rating='bad' returns only the bad-rated decision."""
        compass.add_decision("auth approach alpha", "store passwords in plaintext", "bad", db_path=db)
        compass.add_decision("auth approach beta", "hash passwords with bcrypt", "good", db_path=db)
        bad = compass.query_decisions("passwords", rating="bad", db_path=db)
        assert len(bad) == 1
        assert bad[0]["rating"] == "bad"
        assert "plaintext" in bad[0]["decision"]

    def test_invalid_rating_filter_raises(self, db):
        """An unknown rating filter raises ValueError."""
        compass.add_decision("ctx", "dec", "good", db_path=db)
        with pytest.raises(ValueError):
            compass.query_decisions("ctx", rating="terrible", db_path=db)


class TestStats:
    """stats counts by rating, by status, and total."""

    def test_stats_counts(self, db):
        """stats reports correct totals broken down by rating and status."""
        compass.add_decision("c1", "d1", "good", db_path=db)
        compass.add_decision("c2", "d2", "good", db_path=db)
        compass.add_decision("c3", "d3", "bad", db_path=db)
        archived_id = compass.add_decision("c4", "d4", "interesting", db_path=db)
        compass.archive(archived_id, db_path=db)

        s = compass.stats(db_path=db)
        assert s["total"] == 4
        assert s["by_rating"]["good"] == 2
        assert s["by_rating"]["bad"] == 1
        assert s["by_rating"]["interesting"] == 1
        assert s["by_rating"]["impressive"] == 0
        assert s["by_status"]["active"] == 3
        assert s["by_status"]["archived"] == 1

    def test_stats_empty_db(self, db):
        """stats on an empty DB returns zeroed counts for all keys."""
        s = compass.stats(db_path=db)
        assert s["total"] == 0
        assert s["by_rating"] == {"good": 0, "bad": 0, "impressive": 0, "interesting": 0}
        assert s["by_status"] == {"active": 0, "archived": 0}


class TestRate:
    """rate() changes the rating of an existing decision."""

    def test_rate_changes_rating(self, db):
        """rate updates an existing decision's rating and returns True."""
        did = compass.add_decision("revisited choice", "the chosen path", "good", db_path=db)
        assert compass.rate(did, "bad", db_path=db) is True
        hit = compass.query_decisions("revisited", db_path=db)[0]
        assert hit["rating"] == "bad"

    def test_rate_missing_id_returns_false(self, db):
        """rate on a non-existent id returns False (no silent create)."""
        compass.add_decision("ctx", "dec", "good", db_path=db)
        assert compass.rate(9999, "bad", db_path=db) is False

    def test_rate_invalid_rating_raises(self, db):
        """rate with an invalid rating raises ValueError."""
        did = compass.add_decision("ctx", "dec", "good", db_path=db)
        with pytest.raises(ValueError):
            compass.rate(did, "nope", db_path=db)


class TestArchive:
    """archive() removes a decision from active query results."""

    def test_archive_removes_from_active_query(self, db):
        """An archived decision no longer appears in active query results."""
        did = compass.add_decision("archivable context", "some decision", "good", db_path=db)
        assert len(compass.query_decisions("archivable", db_path=db)) == 1
        assert compass.archive(did, db_path=db) is True
        assert compass.query_decisions("archivable", db_path=db) == []

    def test_archive_missing_id_returns_false(self, db):
        """archive on a non-existent id returns False."""
        assert compass.archive(9999, db_path=db) is False


class TestReview:
    """review() surfaces one active entry and stamps last_reviewed."""

    def test_review_returns_entry_and_stamps(self, db):
        """review returns an entry and stamps its last_reviewed date."""
        compass.add_decision("review me context", "a reviewable decision", "good", db_path=db)
        result = compass.review(db_path=db, reviewed_on="2026-06-16")
        assert result is not None
        assert result["last_reviewed"] == "2026-06-16"

    def test_review_prefers_never_reviewed_first(self, db):
        """review surfaces a never-reviewed (NULL last_reviewed) entry before reviewed ones."""
        first = compass.add_decision("alpha context", "alpha decision", "good", db_path=db)
        second = compass.add_decision("beta context", "beta decision", "good", db_path=db)
        # First review picks one of the two NULL-last_reviewed rows and stamps it.
        picked = compass.review(db_path=db, reviewed_on="2026-06-10")
        assert picked is not None
        assert picked["id"] in (first, second)
        # The other row is still NULL → it must be surfaced next (NULL-first).
        other = second if picked["id"] == first else first
        next_picked = compass.review(db_path=db, reviewed_on="2026-06-11")
        assert next_picked is not None
        assert next_picked["id"] == other
        assert next_picked["last_reviewed"] == "2026-06-11"

    def test_review_none_when_empty(self, db):
        """review returns None when there are no active decisions."""
        assert compass.review(db_path=db) is None

    def test_review_skips_archived(self, db):
        """review ignores archived decisions and returns None when only archived exist."""
        did = compass.add_decision("only entry", "decision", "good", db_path=db)
        compass.archive(did, db_path=db)
        assert compass.review(db_path=db) is None


class TestFts5Ranking:
    """FTS5 BM25 ranking returns the more relevant entry first."""

    def test_more_relevant_first(self, db):
        """The entry with denser keyword matches ranks ahead of the sparse one."""
        # Entry A mentions 'caching' once; entry B mentions it repeatedly and
        # in multiple fields → B should rank above A for the term 'caching'.
        compass.add_decision(
            "A general note about performance",
            "We briefly touched on caching",
            "interesting",
            db_path=db,
        )
        compass.add_decision(
            "Caching strategy for the API",
            "Add a caching layer with caching invalidation",
            "good",
            note="caching is the dominant theme here",
            tags="caching,performance",
            db_path=db,
        )
        results = compass.query_decisions("caching", limit=5, db_path=db)
        assert len(results) == 2
        # The caching-heavy entry ranks first.
        assert results[0]["context"].startswith("Caching strategy")
        assert results[0]["rating"] == "good"


class TestInputValidation:
    """Bad input raises, never silently no-ops."""

    def test_empty_context_raises(self, db):
        """add_decision rejects an empty/whitespace context."""
        with pytest.raises(ValueError):
            compass.add_decision("   ", "dec", "good", db_path=db)

    def test_empty_decision_raises(self, db):
        """add_decision rejects an empty decision."""
        with pytest.raises(ValueError):
            compass.add_decision("ctx", "", "good", db_path=db)

    def test_invalid_rating_raises(self, db):
        """add_decision rejects an out-of-range rating."""
        with pytest.raises(ValueError):
            compass.add_decision("ctx", "dec", "meh", db_path=db)

    def test_invalid_source_raises(self, db):
        """add_decision rejects an unknown source."""
        with pytest.raises(ValueError):
            compass.add_decision("ctx", "dec", "good", source="stranger", db_path=db)

    def test_empty_query_raises(self, db):
        """query_decisions rejects an empty query string."""
        with pytest.raises(ValueError):
            compass.query_decisions("   ", db_path=db)

    def test_nonpositive_limit_raises(self, db):
        """query_decisions rejects a non-positive limit."""
        compass.add_decision("ctx", "dec", "good", db_path=db)
        with pytest.raises(ValueError):
            compass.query_decisions("ctx", limit=0, db_path=db)


class TestSupersedes:
    """supersedes column, atomic archive+link, idempotent migration (DPLAN-0246)."""

    def test_add_with_supersedes_archives_and_links(self, db):
        """--supersedes links the corrector AND archives the target, atomically."""
        old = compass.add_decision("old auth ctx", "use sessions", "good", db_path=db)
        new = compass.add_decision("new auth ctx", "switch to JWT", "good", db_path=db, supersedes=old)
        # The corrector row links back to what it replaced.
        hit = compass.query_decisions("JWT", db_path=db)[0]
        assert hit["supersedes"] == old
        # The old entry is archived → gone from the active query.
        assert compass.query_decisions("sessions", db_path=db) == []
        # With include_archived it reappears, pointing FORWARD to its successor.
        arch = compass.query_decisions("sessions", include_archived=True, db_path=db)[0]
        assert arch["status"] == "archived"
        assert arch["superseded_by"] == new

    def test_supersedes_nonexistent_raises_no_partial_write(self, db):
        """A bad --supersedes id errors cleanly and leaves NO partial write."""
        with pytest.raises(ValueError):
            compass.add_decision("ctx", "dec", "good", db_path=db, supersedes=9999)
        assert compass.stats(db_path=db)["total"] == 0

    def test_supersedes_defaults_none(self, db):
        """A plain add has supersedes=None and superseded_by=None."""
        compass.add_decision("plain ctx", "plain dec", "good", db_path=db)
        hit = compass.query_decisions("plain", db_path=db)[0]
        assert hit["supersedes"] is None
        assert hit["superseded_by"] is None

    def test_active_hit_shows_its_supersedes_pointer(self, db):
        """An ACTIVE corrector still exposes its supersedes pointer on query."""
        old = compass.add_decision("legacy topic zzz", "old way", "bad", db_path=db)
        compass.add_decision("current topic zzz", "new way", "good", db_path=db, supersedes=old)
        hit = compass.query_decisions("current", db_path=db)[0]
        assert hit["supersedes"] == old
        assert hit["superseded_by"] is None  # nothing supersedes the corrector

    def test_migration_idempotent_repeated_connects(self, db):
        """Re-opening the DB re-runs migration harmlessly; column stays present."""
        compass.add_decision("ctx one", "dec one", "good", db_path=db)
        column_present_per_connect = []
        for _ in range(3):
            conn = store._connect(db)
            try:
                cols = {r["name"] for r in conn.execute("PRAGMA table_info(decisions)")}
            finally:
                conn.close()
            column_present_per_connect.append("supersedes" in cols)
        assert column_present_per_connect == [True, True, True]

    def test_migration_adds_column_to_legacy_db(self, db):
        """A pre-supersedes DB gets the column added in via _connect migration."""
        # Build a legacy `decisions` table WITHOUT supersedes, as older builds had.
        conn = sqlite3.connect(str(db))
        conn.execute(
            "CREATE TABLE decisions ("
            "id INTEGER PRIMARY KEY, created TEXT, context TEXT NOT NULL, "
            "decision TEXT NOT NULL, rating TEXT NOT NULL, note TEXT, tags TEXT, "
            "source TEXT, score INTEGER, status TEXT DEFAULT 'active', "
            "last_reviewed TEXT, times_surfaced INTEGER DEFAULT 0)"
        )
        conn.commit()
        conn.close()
        # Legacy table lacks the column...
        conn = sqlite3.connect(str(db))
        pre = {r[1] for r in conn.execute("PRAGMA table_info(decisions)")}
        conn.close()
        assert "supersedes" not in pre
        # ...a store connect migrates it in (CREATE IF NOT EXISTS is a no-op here).
        conn = store._connect(db)
        try:
            post = {r["name"] for r in conn.execute("PRAGMA table_info(decisions)")}
        finally:
            conn.close()
        assert "supersedes" in post


class TestFindConflicts:
    """Write-time conflict check: FTS over ACTIVE rows, sanitized, side-effect-free."""

    def test_finds_overlapping_active_row(self, db):
        """A would-be entry surfaces an existing active row it overlaps."""
        compass.add_decision("caching strategy for the API", "add a redis caching layer", "good", db_path=db)
        hits = compass.find_conflicts("caching approach", "use a caching layer", db_path=db)
        assert len(hits) >= 1
        assert any("caching" in h["context"] for h in hits)

    def test_ignores_archived_rows(self, db):
        """Conflict check searches active rows only — archived never surfaces."""
        did = compass.add_decision("archived topic xyzzy", "some decision", "good", db_path=db)
        compass.archive(did, db_path=db)
        assert compass.find_conflicts("xyzzy topic", "another decision", db_path=db) == []

    def test_no_side_effects_on_times_surfaced(self, db):
        """The advisory must NOT bump times_surfaced — it is not a real surface."""
        compass.add_decision("surfacing guard ctx", "a decision here", "good", db_path=db)
        compass.find_conflicts("surfacing guard", "a decision", db_path=db)
        hit = compass.query_decisions("surfacing", db_path=db)[0]
        assert hit["times_surfaced"] == 1  # only the query above counted

    def test_sanitizes_fts_special_chars(self, db):
        """Raw FTS5 syntax characters must not crash MATCH — sanitized to literals."""
        compass.add_decision("special ctx", "a normal decision", "good", db_path=db)
        weird = 'broken " ( ) * : query -term AND OR NOT'
        result = compass.find_conflicts(weird, "more * (text) ^caret", db_path=db)
        assert result == []  # no token overlaps, and no FTS5 syntax error either
        # The same syntax characters around a real token still find the row:
        # sanitising quotes the words, it does not drop them.
        hits = compass.find_conflicts('special " ( ) * :', "-normal AND OR NOT", db_path=db)
        assert [hit["decision"] for hit in hits] == ["a normal decision"]

    def test_empty_text_returns_empty(self, db):
        """Text with no usable tokens yields no conflicts (and no crash)."""
        assert compass.find_conflicts("   ", "   ", db_path=db) == []


class TestSetNote:
    """note edits persist AND re-index immediately via the FTS5 UPDATE trigger."""

    def test_set_note_updates_and_returns_true(self, db):
        """set_note stores the note and reports the row was changed."""
        did = compass.add_decision("note ctx", "note dec", "good", db_path=db)
        assert compass.set_note(did, "a fresh observation", db_path=db) is True
        hit = compass.query_decisions("note ctx", db_path=db)[0]
        assert hit["note"] == "a fresh observation"

    def test_note_edit_is_immediately_fts_searchable(self, db):
        """PROOF: the decisions_au trigger re-indexes a note UPDATE for FTS."""
        did = compass.add_decision("indexing ctx", "indexing dec", "good", db_path=db)
        # 'zebra' appears nowhere yet.
        assert compass.query_decisions("zebra", db_path=db) == []
        compass.set_note(did, "mentions zebra now", db_path=db)
        # Immediately findable through the freshly re-indexed note column.
        found = compass.query_decisions("zebra", db_path=db)
        assert len(found) == 1
        assert found[0]["id"] == did

    def test_set_note_missing_id_returns_false(self, db):
        """set_note on a non-existent id returns False (no silent create)."""
        assert compass.set_note(9999, "nope", db_path=db) is False


class TestScoreRemoved:
    """score is gone from every Python surface (DPLAN-0246 seedgo ruling)."""

    def test_score_not_in_decision_columns(self):
        """The code-level column list no longer names score."""
        assert "score" not in store._DECISION_COLUMNS

    def test_score_absent_from_query_dict(self, db):
        """Query result dicts carry no score key."""
        compass.add_decision("score ctx", "score dec", "good", db_path=db)
        hit = compass.query_decisions("score", db_path=db)[0]
        assert "score" not in hit

    def test_score_absent_from_review_dict(self, db):
        """Review result dicts carry no score key."""
        compass.add_decision("review score ctx", "dec", "good", db_path=db)
        result = compass.review(db_path=db)
        assert result is not None
        assert "score" not in result


class TestRecall:
    """recall_decisions/mark_surfaced — the Track 2 ambient-recall read path."""

    def test_recall_returns_scored_active_candidates(self, db):
        """Raw prompt text yields active hits, each with relevance in (0, 1)."""
        compass.add_decision("vectorization pipeline ctx", "salt vector ids", "good", db_path=db)
        hits = compass.recall_decisions("we are working on the vectorization pipeline", db_path=db)
        assert hits and hits[0]["decision"] == "salt vector ids"
        assert 0.0 < hits[0]["relevance"] < 1.0

    def test_recall_is_side_effect_free(self, db):
        """A recall does NOT bump times_surfaced — candidates are not surfacings."""
        compass.add_decision("recall counter ctx", "stay untouched", "good", db_path=db)
        rid = compass.recall_decisions("recall counter", db_path=db)[0]["id"]
        compass.recall_decisions("recall counter", db_path=db)
        hit = compass.query_decisions("untouched", db_path=db)[0]
        assert hit["id"] == rid
        # query_decisions itself increments once; recalls added nothing.
        assert hit["times_surfaced"] == 1

    def test_recall_excludes_archived(self, db):
        """Archived rows never come back as ambient candidates."""
        rid = compass.add_decision("archived recall ctx", "dead ruling", "bad", db_path=db)
        compass.archive(rid, db_path=db)
        assert compass.recall_decisions("archived recall dead ruling", db_path=db) == []

    def test_recall_survives_fts_syntax_in_prompt(self, db):
        """FTS5 syntax characters in a prompt cannot crash the MATCH."""
        compass.add_decision("syntax safety ctx", "quote all tokens", "good", db_path=db)
        hits = compass.recall_decisions('safety AND (tokens) OR "quote" NEAR *:^-', db_path=db)
        assert hits and hits[0]["decision"] == "quote all tokens"

    def test_recall_empty_prompt_returns_empty(self, db):
        """No usable tokens → empty list, no error."""
        assert compass.recall_decisions("", db_path=db) == []
        assert compass.recall_decisions("()!@#$", db_path=db) == []

    def test_recall_ranks_most_relevant_first(self, db):
        """Denser overlap outranks a single shared token."""
        compass.add_decision("alpha beta gamma delta", "dense match", "good", db_path=db)
        compass.add_decision("alpha unrelated topic here", "sparse match", "good", db_path=db)
        hits = compass.recall_decisions("alpha beta gamma delta", limit=2, db_path=db)
        assert hits[0]["decision"] == "dense match"
        assert hits[0]["relevance"] > hits[1]["relevance"]

    def test_recall_invalid_limit_raises(self, db):
        """Non-positive limit fails honestly."""
        with pytest.raises(ValueError):
            compass.recall_decisions("anything", limit=0, db_path=db)

    def test_mark_surfaced_counts_only_injected(self, db):
        """mark_surfaced increments exactly the ids the caller reports."""
        a = compass.add_decision("mark ctx one", "dec one xyzzy", "good", db_path=db)
        b = compass.add_decision("mark ctx two", "dec two xyzzy", "good", db_path=db)
        assert compass.mark_surfaced([a], db_path=db) == 1
        hits = {h["id"]: h for h in compass.query_decisions("xyzzy", limit=5, db_path=db)}
        # query bumps both by 1; only a carries the extra mark_surfaced bump.
        assert hits[a]["times_surfaced"] == 2
        assert hits[b]["times_surfaced"] == 1

    def test_mark_surfaced_empty_list_is_noop(self, db):
        """An empty id list returns 0 and touches nothing."""
        assert compass.mark_surfaced([], db_path=db) == 0

    def test_recall_stopwords_do_not_drive_ranking(self, db):
        """Filler words in the prompt cannot outrank topic words (FPLAN-0332)."""
        compass.add_decision(
            "docker sop ctx with the and on for filler heavy text",
            "push dev first clone in container",
            "good",
            db_path=db,
        )
        compass.add_decision(
            "compass curation ctx",
            "supersedes links archive corrections",
            "good",
            db_path=db,
        )
        hits = compass.recall_decisions(
            "lets keep working on the compass supersedes links and curation",
            limit=2,
            db_path=db,
        )
        assert hits[0]["decision"] == "supersedes links archive corrections"

    def test_recall_all_stopword_prompt_returns_empty(self, db):
        """A prompt made only of stopwords yields no candidates, no error."""
        compass.add_decision("some ctx", "some dec", "good", db_path=db)
        assert compass.recall_decisions("what is it and how do we", db_path=db) == []
