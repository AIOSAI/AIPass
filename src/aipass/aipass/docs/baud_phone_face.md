# The phone face — `aipass baud`

*How the phone bundle and `baud-cli` get onto a machine, and what refuses an install.*

@api's host server serves @baud's phone bundle. A source checkout builds it with
node; everyone else gets it from a baud release (FPLAN-0587). AIPass never
vendors the bundle, so the two licences stay apart.

- **Fetch.** The public release download first. `latest` resolves the tag before
  downloading, because the asset name carries it, and both files come from that
  one tag. On 403/404 with a token (`GITHUB_TOKEN`, else the gh CLI's login), the
  GitHub API route with `Accept: application/octet-stream`; the token rides an
  unredirected header, so it never reaches the storage host the API redirects
  to. No token and a 404 says the repo may be private and names `--from`.
- **Verify.** The tarball's line in `SHA256SUMS.txt` (sha256sum format). No line
  means refused. A mismatch means refused, and a download is deleted; a `--from`
  file stays, because it is yours.
- **Unpack.** Every member is judged before anything is written: no absolute
  names, `..`, links, devices or fifos, no directory but `assets/`, and
  `phone.html` plus `assets/` required. Files are copied by this code, never
  extracted with archive modes or owners.
- **Swap.** Into `.phone.staging` beside the destination, marker
  `.baud-phone.json` (tag, sha256, installed_at, source) written last, then
  `phone` -> `phone.prev`, staging -> `phone`, prev dropped. If the swap fails,
  the previous install goes back. A non-empty destination without the marker is
  refused: it is not an install this command made.
- **baud-cli** (FPLAN-0589). The headless binary, `baud-cli-<tag>-linux-x86_64`,
  from the same release and the same door. It is verified against the same
  `SHA256SUMS.txt` BEFORE the face is placed, so a bad binary refuses the whole
  install. It lands at `bin/baud-cli` beside the face's directory: bytes copied
  into `bin/.baud-cli.staging`, hashed again, 0755, then `baud-cli` ->
  `baud-cli.prev` (kept) and staging -> `baud-cli`. The marker `.baud-cli.json`
  (tag, sha256, installed_at, source) is written last. A `baud-cli` with no marker
  is refused. Releases build for linux-x86_64 only: on any other platform, or for
  a release that carries no binary, the install says so in one line, lands the
  face alone and still exits 0.
- **Point.** `set_face_dir(dest)` and `set_baud_bin(path)` on @api's host config,
  called in-process so @api validates each path. aipass never writes api's config
  file. A running host api only sees a new face directory after a restart, and the
  command says so; it uses a new binary from its next request.

A `--dest` install points @api at the scratch location too. Undo with
`drone @api host-api set-config --face-dir <previous|default> --baud-bin <previous|default>`.

`aipass install` runs this as step 4, best-effort: offline, a private repo or a
missing token prints one line plus the retry command, and the install carries on.

## The command forms

`aipass baud --help` is the reference. The shapes, in short:

- `baud install` — the latest release's face and binary, verified, placed, pointed at.
- `baud install --tag vX.Y.Z` — a named release instead of the latest.
- `baud install --from TAR [--sums SUMS] [--binary BIN]` — files on disk, no network.
  Without `--sums`, `SHA256SUMS.txt` beside the tarball; no sums, no install.
  `--binary` lands a baud-cli too, verified against the same sums.
- `baud install --dest DIR` — face in DIR, baud-cli in `DIR/../bin`.
- `baud install --dry-run` — walk the steps and write nothing.
- `baud status [--dest DIR]` — two rows, face and baud-cli: installed tag and
  sha256, `phone.html` / executable, where @api's face dir and baud binary point.

Code: [`apps/modules/baud.py`](../apps/modules/baud.py) and the handler group
[`apps/handlers/baud/`](../apps/handlers/baud) — `fetch.py`, `verify.py`,
`unpack.py`, `binary.py`, `installer.py`, `point.py`.

---

[← Back to the AIPASS README](../README.md)
