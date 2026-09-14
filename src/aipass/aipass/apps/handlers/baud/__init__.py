"""baud — install @baud's phone face and baud-cli from a release: fetch, verify, unpack, land, point.

FPLAN-0587 (the face), FPLAN-0589 (baud-cli).
"""

from aipass.aipass.apps.handlers.baud.binary import (  # type: ignore[import-not-found]
    BIN_MARKER,
    RELEASE_PLATFORM,
    baud_root,
    bin_path,
    binary_asset_name,
    install_binary,
    platform_slug,
    read_binary_install,
)
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
    BinaryOutcome,
    InstallOutcome,
    install_from_file,
    install_from_release,
    local_tag,
)
from aipass.aipass.apps.handlers.baud.point import (  # type: ignore[import-not-found]
    RESTART_HINT,
    PointResult,
    api_baud_bin_state,
    api_face_dir_state,
    phone_url,
    point_api_at,
    point_api_at_binary,
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
    "BIN_MARKER",
    "LATEST",
    "MARKER_NAME",
    "RELEASE_PLATFORM",
    "RESTART_HINT",
    "SUMS_ASSET",
    "BinaryOutcome",
    "FetchError",
    "FetchedRelease",
    "InstallOutcome",
    "PointResult",
    "UnpackError",
    "VerifyError",
    "api_baud_bin_state",
    "api_face_dir_state",
    "baud_root",
    "bin_path",
    "binary_asset_name",
    "extract_bundle",
    "fetch_release",
    "install_binary",
    "install_bundle",
    "install_from_file",
    "install_from_release",
    "local_tag",
    "parse_sums",
    "phone_asset_name",
    "phone_url",
    "platform_slug",
    "point_api_at",
    "point_api_at_binary",
    "read_binary_install",
    "read_install",
    "resolve_token",
    "sha256_file",
    "validate_members",
    "validate_tag",
    "verify_tarball",
]
