"""Root conftest for sentry — exclude templates from pytest collection."""

collect_ignore_glob = ["templates/*"]
