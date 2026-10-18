# =================== AIPass ====================
# Name: admin_grant.py
# Description: Birth-certificate admin grant — keygen, mint (sign), verify (FPLAN-0401)
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-10-17
# =============================================

"""
Birth-certificate admin grant for devpulse (DPLAN-0288 / FPLAN-0401).

The contract lives in FPLAN-0401 and @ai_mail mirrors it for the dispatch lane: change both sides together.
The key is outside every repo but readable by the shared OS user: the HMAC is tamper evidence, not secrecy.
Never log or print key material.
"""

import hmac
import hashlib
import json
import os
import secrets
import stat
from datetime import date
from pathlib import Path

from aipass.prax import logger
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.module_root import module_file

_BRANCH_ROOT = module_file(__file__).parents[3]

DEFAULT_KEY_PATH = Path.home() / ".aipass" / "admin_grant.key"
DEFAULT_CERT_PATH = _BRANCH_ROOT / "artifacts" / "birth_certificate.json"

ADMIN_HOLDER = "devpulse"  # constant by design — the grant is not parameterizable
SIGNATURE_ALGO = "hmac-sha256"


def canonical_payload(cert: dict) -> bytes:
    """Canonical signing payload: full cert WITHOUT ``signature``; the contract's exact dumps, so writers agree."""
    unsigned = {k: v for k, v in cert.items() if k != "signature"}
    return json.dumps(unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _read_key(key_path: Path) -> bytes | None:
    """Read key bytes (64 hex chars -> 32 bytes). None if missing/invalid: a corrupt key fails closed."""
    if not key_path.exists():
        return None
    try:
        return bytes.fromhex(key_path.read_text(encoding="utf-8").strip())
    except ValueError:
        logger.error("[admin_grant] key file exists but is not valid hex — treating as missing")
        return None


def compute_signature(cert: dict, key: bytes) -> str:
    """HMAC-SHA256 hex signature over the canonical payload."""
    return hmac.new(key, canonical_payload(cert), hashlib.sha256).hexdigest()


def generate_key(key_path: Path = DEFAULT_KEY_PATH, force: bool = False) -> tuple[bool, str]:
    """Create the signing key (64 hex chars, 0600). Refuses to overwrite; the message never holds key material."""
    if key_path.exists() and not force:
        return False, f"key already exists at {key_path} — refusing to overwrite (use force)"

    key_path.parent.mkdir(parents=True, exist_ok=True)
    key_path.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
    key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    logger.info("[admin_grant] signing key generated at %s", key_path)
    json_handler.log_operation("admin_grant", {"op": "keygen", "ok": True}, module_name="admin_grant")
    return True, f"signing key generated at {key_path} (0600)"


def mint_grant(
    cert_path: Path = DEFAULT_CERT_PATH,
    key_path: Path = DEFAULT_KEY_PATH,
    granted_by: str = "owner",
) -> tuple[bool, str]:
    """Add the admin privilege block to devpulse's existing birth certificate and sign it; never creates one."""
    key = _read_key(key_path)
    if key is None:
        return False, f"no signing key at {key_path} — run keygen first"

    if not cert_path.exists():
        return False, f"birth certificate not found at {cert_path}"

    try:
        cert = json.loads(cert_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[admin_grant] mint refused — cert unreadable: %s", exc)
        return False, f"birth certificate unreadable: {exc}"

    if cert.get("owner") != ADMIN_HOLDER or cert.get("type") != "birth_certificate":
        return False, (
            f"refusing to mint: cert owner={cert.get('owner')!r} type={cert.get('type')!r} — "
            f"only {ADMIN_HOLDER}'s birth certificate ever carries the admin grant"
        )

    cert["privileges"] = {
        "admin": True,
        "granted_by": granted_by,
        "granted": date.today().isoformat(),
    }
    cert["signature"] = {"algo": SIGNATURE_ALGO, "value": compute_signature(cert, key)}

    cert_path.write_text(json.dumps(cert, indent=2) + "\n", encoding="utf-8")
    logger.info("[admin_grant] admin grant minted + signed on %s", cert_path)
    json_handler.log_operation("admin_grant", {"op": "mint", "ok": True}, module_name="admin_grant")
    return True, f"admin grant minted + signed on {cert_path}"


def _resolve_verified_caller() -> str:
    """Resolve the caller from the env rail ONLY, or "": the process cwd is never consulted (fail closed)."""
    branch = os.environ.get("AIPASS_CALLER_BRANCH", "")
    if branch:
        return branch.lstrip("@").lower()

    caller_cwd_env = os.environ.get("AIPASS_CALLER_CWD", "")
    if not caller_cwd_env:
        return ""

    caller_cwd = Path(caller_cwd_env)
    for candidate in [caller_cwd, *caller_cwd.parents]:
        passport = candidate / ".trinity" / "passport.json"
        if passport.exists():
            try:
                data = json.loads(passport.read_text(encoding="utf-8"))
                name = data.get("branch_info", {}).get("branch_name", "")
                return (name or candidate.name).lstrip("@").lower()
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[admin_grant] caller passport unreadable at %s: %s", candidate, exc)
                return ""  # unreadable passport = unverifiable = refuse
    return ""


def _find_registry(start: Path) -> Path | None:
    """Walk up from ``start`` for AIPASS_REGISTRY.json (the root registry)."""
    for candidate in [start, *start.parents]:
        registry = candidate / "AIPASS_REGISTRY.json"
        if registry.exists():
            return registry
    return None


def verify_admin_grant(
    key_path: Path = DEFAULT_KEY_PATH,
    registry_path: Path | None = None,
) -> tuple[bool, str]:
    """Full 5-leg verification per THE CONTRACT: (ok, reason naming the failed leg); nothing passes by default."""
    caller = _resolve_verified_caller()
    if caller != ADMIN_HOLDER:
        return False, f"leg1 caller: verified caller is {caller or 'unverifiable'!r}, not {ADMIN_HOLDER}"

    # The cert path comes from the registry entry, never from the caller.
    registry_file = registry_path or _find_registry(_BRANCH_ROOT)
    if registry_file is None or not registry_file.exists():
        return False, "leg2 cert-path: AIPASS_REGISTRY.json not found"
    try:
        registry = json.loads(registry_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[admin_grant] verify refused — registry unreadable: %s", exc)
        return False, f"leg2 cert-path: registry unreadable: {exc}"

    entry = next(
        (b for b in registry.get("branches", []) if b.get("name", "").lower() == ADMIN_HOLDER),
        None,
    )
    if entry is None:
        return False, f"leg2 cert-path: no {ADMIN_HOLDER} entry in registry"

    entry_path = Path(entry.get("path", ""))
    if not entry_path.is_absolute():
        entry_path = registry_file.parent / entry_path
    cert_path = entry_path / "artifacts" / "birth_certificate.json"
    if not cert_path.exists():
        return False, f"leg2 cert-path: no birth certificate at registry-recorded home {entry_path}"

    try:
        cert = json.loads(cert_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("[admin_grant] verify refused — cert unreadable: %s", exc)
        return False, f"leg3 content: certificate unreadable: {exc}"
    if cert.get("owner") != ADMIN_HOLDER or cert.get("type") != "birth_certificate":
        return False, "leg3 content: certificate owner/type mismatch"
    if cert.get("privileges", {}).get("admin") is not True:
        return False, "leg3 content: certificate carries no admin privilege"

    key = _read_key(key_path)
    if key is None:
        return False, f"leg4 signature: no signing key at {key_path} — lane dark until ceremony"
    signature = cert.get("signature", {})
    if signature.get("algo") != SIGNATURE_ALGO or not signature.get("value"):
        return False, "leg4 signature: missing or wrong-algo signature block"
    if not hmac.compare_digest(signature["value"], compute_signature(cert, key)):
        return False, "leg4 signature: signature mismatch — certificate tampered or foreign key"

    if entry.get("admin") is not True:
        return False, f"leg5 registry: {ADMIN_HOLDER} entry lacks admin flag (ceremony incomplete)"

    return True, "admin grant verified"


def grant_status(
    cert_path: Path = DEFAULT_CERT_PATH,
    key_path: Path = DEFAULT_KEY_PATH,
    registry_path: Path | None = None,
) -> dict:
    """Ceremony/lane state at a glance. Never exposes key material."""
    cert: dict = {}
    if cert_path.exists():
        try:
            cert = json.loads(cert_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("[admin_grant] status — cert unreadable: %s", exc)
            cert = {}
    ok, reason = verify_admin_grant(key_path=key_path, registry_path=registry_path)
    return {
        "key_present": key_path.exists(),
        "cert_present": cert_path.exists(),
        "privileges": cert.get("privileges", {}),
        "signed": bool(cert.get("signature", {}).get("value")),
        "verified": ok,
        "verify_reason": reason,
    }
