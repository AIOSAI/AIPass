"""baud — install @baud's phone face from a release: fetch, verify, unpack, point (FPLAN-0587)."""

from aipass.aipass.apps.handlers.baud.fetch import (  # type: ignore[import-not-found]
    LATEST,
    SUMS_ASSET,
    FetchedRelease,
    FetchError,
    fetch_release,
    phone_asset_name,
    resolve_token,
    validate_tag,
)
from aipass.aipass.apps.handlers.baud.installer import (  # type: ignore[import-not-found]
    InstallOutcome,
    install_from_file,
    install_from_release,
    local_tag,
)
from aipass.aipass.apps.handlers.baud.point import (  # type: ignore[import-not-found]
    RESTART_HINT,
    PointResult,
    api_face_dir_state,
    phone_url,
    point_api_at,
)
from aipass.aipass.apps.handlers.baud.unpack import (  # type: ignore[import-not-found]
    MARKER_NAME,
    UnpackError,
    extract_bundle,
    install_bundle,
    read_install,
    validate_members,
)
from aipass.aipass.apps.handlers.baud.verify import (  # type: ignore[import-not-found]
    VerifyError,
    parse_sums,
    sha256_file,
    verify_tarball,
)

__all__ = [
    "LATEST",
    "MARKER_NAME",
    "RESTART_HINT",
    "SUMS_ASSET",
    "FetchError",
    "FetchedRelease",
    "InstallOutcome",
    "PointResult",
    "UnpackError",
    "VerifyError",
    "api_face_dir_state",
    "extract_bundle",
    "fetch_release",
    "install_bundle",
    "install_from_file",
    "install_from_release",
    "local_tag",
    "parse_sums",
    "phone_asset_name",
    "phone_url",
    "point_api_at",
    "read_install",
    "resolve_token",
    "sha256_file",
    "validate_members",
    "validate_tag",
    "verify_tarball",
]
