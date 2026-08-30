"""Red-first pins for FPLAN-0460: discovery delegates to registry_scope."""

from unittest.mock import patch

from aipass.daemon.apps.handlers.schedule.discovery import active_citizens

SCOPE = "aipass.daemon.apps.handlers.schedule.discovery.registry_scope"


class TestDelegatesToRegistryScope:
    """The fleet definition is @memory's, consumed — not re-implemented here."""

    def test_a_branch_only_registry_scope_knows_is_discovered(self, tmp_path):
        """The whole point: externals arrive with no daemon code change.

        A record fleet_branches() returns must reach active_citizens() even
        though NO daemon-side registry read could have produced it — the path
        is outside this repo entirely.
        """
        external = tmp_path / "elsewhere" / "src" / "wren" / "wren"
        external.mkdir(parents=True)
        fake = [{"name": "wren", "path": external, "registry": "WREN_REGISTRY.json", "email": "@wren"}]

        with patch(f"{SCOPE}.fleet_branches", return_value=fake):
            citizens = active_citizens()

        assert [c["email"] for c in citizens] == ["@wren"]
        assert citizens[0]["path"] == external
        assert citizens[0]["dir_name"] == "wren"

    def test_an_addressless_branch_is_refused_and_named(self, tmp_path, caplog):
        """@memory keeps addressless branches; daemon cannot use them.

        Their ruling: absent email is None and the branch is KEPT, because
        path-based lanes still want it. Daemon is email-addressed, so it
        refuses on its own terms — but never silently.
        """
        home = tmp_path / "nameless"
        home.mkdir()
        fake = [{"name": "nameless", "path": home, "registry": "AIPASS_REGISTRY.json", "email": None}]

        with patch(f"{SCOPE}.fleet_branches", return_value=fake):
            with caplog.at_level("ERROR"):
                citizens = active_citizens()

        assert citizens == []
        assert "nameless" in caplog.text
