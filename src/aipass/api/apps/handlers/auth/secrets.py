# =================== AIPass ====================
# Name: secrets.py
# Description: Secrets Store Handler — values rest in the login keyring; files are only the import source
# Version: 2.0.0
# Created: 2026-06-15
# Modified: 2026-10-22
# =============================================

"""Secrets Store Handler"""

import json
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import keyring
from keyring.backends import chainer, fail, null
from keyring.errors import KeyringError

from aipass.prax import logger
from aipass.api.apps.handlers.json import json_handler

SERVICE = "aipass"

# The import source for migrate, and the root of host_api/'s lock and receipts. Never read by get_secret.
SECRETS_BASE = Path.home() / ".secrets" / "aipass"

_TOKEN_KEYS = ("bot_token", "api_key", "token", "secret", "password", "key")

_GOOGLE_FILES = {"google_client_secret.json": "client_secret", "google_creds.json": "creds"}
_ENV_FILE = ".env"
_ENV_KEY_SUFFIX = "_API_KEY"


class SecretsUnavailable(RuntimeError):
    """The keyring cannot hold or give a secret: named by backend class and reason, never a value or a path."""


def get_secret(provider: str, slug: str, as_json: bool = False) -> Optional[Any]:
    """Get a secret from the keyring entry <provider>/<slug>; None when there is no entry."""
    backend = _backend()
    stored = _call(backend, "read", backend.get_password, SERVICE, _name(provider, slug))

    if stored is None:
        # Never the slug: callers pass slugs read out of the store (list_secrets), which CodeQL flags.
        logger.warning("Secret not found under provider %s: no keyring entry for the requested slug", provider)
        return None

    json_handler.log_operation("secret_retrieved", {"provider": provider, "slug": slug})
    return _decode(stored, as_json)


def list_secrets(provider: str) -> List[str]:
    """List the slugs stored for a provider, from its index entry <provider>/."""
    return sorted(_read_index(_backend(), provider))


def set_secret(provider: str, slug: str, value: Union[str, dict], *, as_json: bool = False) -> str:
    """Write a secret to the keyring entry <provider>/<slug> and return that entry's name."""
    backend = _backend()
    name = _name(provider, slug)
    stored = json.dumps(value) if as_json else str(value)
    _call(backend, "write", backend.set_password, SERVICE, name, stored)

    index = _read_index(backend, provider)
    if slug not in index:
        _call(backend, "write", backend.set_password, SERVICE, f"{provider}/", json.dumps(sorted(index + [slug])))

    json_handler.log_operation("secret_written", {"provider": provider, "slug": slug})
    return name


def migrate_store(dry_run: bool = False) -> Dict[str, Any]:
    """Import every file of the store's shapes into the keyring, shredding each once its entry is in."""
    backend = _backend()
    plan, left = _survey(SECRETS_BASE)
    report: Dict[str, Any] = {"backend": _label(backend), "moved": [], "left": left, "failed": []}

    if dry_run:
        report["moved"] = [f"{provider}/{slug}" for _, items, _ in plan for provider, slug, _, _ in items]
        return report

    for path, items, shred in plan:
        try:
            for provider, slug, value, as_json in items:
                set_secret(provider, slug, value, as_json=as_json)
                if _decode(backend.get_password(SERVICE, _name(provider, slug)), as_json) != value:
                    raise SecretsUnavailable(f"The keyring backend {_label(backend)} did not keep a write")
            if shred:
                _shred(path)
        except (SecretsUnavailable, KeyringError, OSError) as e:
            # Ours names the backend and the reason; anyone else's words may carry a path, so only its type.
            reason = str(e) if isinstance(e, SecretsUnavailable) else type(e).__name__
            report["failed"].append((path.relative_to(SECRETS_BASE).as_posix(), reason))
            continue
        for provider, slug, _, _ in items:
            report["moved"].append(f"{provider}/{slug}")
            json_handler.log_operation("secret_migrated", {"provider": provider, "slug": slug})

    return report


def _backend() -> Any:
    """The keyring backend, refused when it cannot hold a secret."""
    backend = keyring.get_keyring()
    reason = _refusal(backend)
    if reason:
        raise SecretsUnavailable(f"The keyring backend {_label(backend)} cannot hold a secret: {reason}")
    return backend


def _label(backend: Any) -> str:
    """A backend named by module and class: keyring's fail and null backends are both just `Keyring`."""
    return f"{type(backend).__module__}.{type(backend).__name__}"


def _refusal(backend: Any) -> Optional[str]:
    """Why a backend cannot hold a secret, or None when it can."""
    if type(backend).__module__.startswith("keyrings.alt"):
        return "it is a plaintext backend"
    if isinstance(backend, fail.Keyring):
        return "no keyring backend is available"
    if isinstance(backend, null.Keyring):
        return "the keyring is switched off"
    if isinstance(backend, chainer.ChainerBackend):
        members = list(backend.backends)
        if not members or any(_refusal(member) for member in members):
            return "its chain holds no keyring, or a plaintext one"
    return None


def _call(backend: Any, verb: str, operation: Callable[..., Any], *args: Any) -> Any:
    """Run one keyring operation, a refusal raised as SecretsUnavailable."""
    try:
        return operation(*args)
    except KeyringError as e:
        # The type alone, and no chain: a backend's message may quote the entry it failed on.
        raise SecretsUnavailable(
            f"The keyring backend {_label(backend)} refused the {verb} ({type(e).__name__})"
        ) from None


def _name(provider: str, slug: str) -> str:
    """The entry's username: <provider>/<slug>."""
    return f"{provider}/{slug}"


def _read_index(backend: Any, provider: str) -> List[str]:
    """The provider's slugs from its index entry; a broken index raises, never an empty list."""
    stored = _call(backend, "read", backend.get_password, SERVICE, f"{provider}/")
    if stored is None:
        return []
    refusal = f"The keyring index entry for provider {provider} is not a list of slugs"
    try:
        index = json.loads(stored)
    except ValueError:
        raise SecretsUnavailable(refusal) from None
    if not isinstance(index, list):
        raise SecretsUnavailable(refusal)
    return [str(slug) for slug in index]


def _decode(stored: str, as_json: bool) -> Any:
    """A stored value as the caller asked: the parsed document, or the string a token key names."""
    try:
        data = json.loads(stored)
    except ValueError:
        logger.debug("A stored value is not a JSON document; returned as stored")
        return stored

    if as_json:
        return data
    if isinstance(data, dict):
        for key in _TOKEN_KEYS:
            if key in data:
                return str(data[key])
        return json.dumps(data)
    return data if isinstance(data, str) else stored


def _survey(base: Path) -> Tuple[List[Tuple[Path, list, bool]], List[str]]:
    """What migrate would move (file, its entries, whether it is shredded) and what it leaves, by name."""
    plan: List[Tuple[Path, list, bool]] = []
    left: List[str] = []
    if not base.is_dir():
        return plan, left

    for entry in sorted(base.iterdir()):
        if entry.is_dir():
            for item in sorted(entry.rglob("*")):
                if not item.is_file():
                    continue
                shape = _file_shape(entry.name, item) if item.parent == entry else None
                _place(plan, left, base, item, [shape] if shape else [], True)
        elif entry.name in _GOOGLE_FILES:
            _place(plan, left, base, entry, _json_entry(entry, "google", _GOOGLE_FILES[entry.name]), True)
        elif entry.name == _ENV_FILE:
            _place(plan, left, base, entry, *_env_entries(entry))
        else:
            left.append(entry.name)
    return plan, left


def _place(plan: list, left: List[str], base: Path, path: Path, items: list, shred: bool) -> None:
    """File a path under plan when it has entries to import, and under left when it stays."""
    if items:
        plan.append((path, items, shred))
    if not items or not shred:
        left.append(path.relative_to(base).as_posix())


def _file_shape(provider: str, path: Path) -> Optional[Tuple[str, str, Any, bool]]:
    """<provider>/<slug>.json or <provider>/<slug> (raw) as an entry; any other file is not a store shape."""
    if path.name.startswith("."):
        return None
    if path.suffix == ".json":
        found = _json_entry(path, provider, path.stem)
        return found[0] if found else None
    if not path.suffix:
        return provider, path.name, path.read_text(encoding="utf-8").strip(), False
    return None


def _json_entry(path: Path, provider: str, slug: str) -> List[Tuple[str, str, Any, bool]]:
    """A JSON file as one entry; an unparseable one is left for the owner."""
    try:
        return [(provider, slug, json.loads(path.read_text(encoding="utf-8")), True)]
    except (ValueError, OSError) as e:
        # The type alone: a parser's message can quote the bytes it choked on.
        logger.warning("A JSON file under provider %s is left in the store (%s)", provider, type(e).__name__)
        return []


def _env_entries(path: Path) -> Tuple[List[Tuple[str, str, Any, bool]], bool]:
    """Each <PROVIDER>_API_KEY=<value> line as <provider>/api_key, and whether nothing else is in the file."""
    items = []
    only_keys = True
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.strip().partition("=")
        key, value = key.strip(), value.strip()
        if not key or key.startswith("#"):
            continue
        if key.endswith(_ENV_KEY_SUFFIX) and value:
            items.append((key[: -len(_ENV_KEY_SUFFIX)].lower(), "api_key", value, False))
        else:
            # Another setting (BLUESKY_HANDLE, ...) is not a store shape: the file stays for the owner's hand.
            only_keys = False
    return items, only_keys


def _shred(path: Path) -> None:
    """Overwrite a file with zeros, fsync, then unlink it."""
    size = path.stat().st_size
    descriptor = os.open(str(path), os.O_WRONLY)
    try:
        os.write(descriptor, b"\0" * size)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.unlink(str(path))
