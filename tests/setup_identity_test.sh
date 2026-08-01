#!/usr/bin/env bash
#
# Regression test for setup.sh's git-identity + user-name flow
# (round-2 install UX: a0f2351e Catch 1 / 43ff5873 Catch 3).
#
# Sources the real is_valid_git_email / is_interactive / resolve_git_identity /
# resolve_user_name / print_action_needed functions out of setup.sh (single
# source of truth — no copy) and drives them against a stubbed `git` so no
# real global git config is ever touched. Exits 0 on all-pass, non-zero on
# any regression.
#
# Run: bash tests/setup_identity_test.sh
set -u

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SETUP="$REPO_ROOT/setup.sh"
TMP="$(mktemp -d)"
FAILURES=0

cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

FN="$TMP/fn.sh"
for fn in print_action_needed is_valid_git_email is_interactive resolve_git_identity resolve_user_name; do
    sed -n "/^${fn}() {/,/^}/p" "$SETUP" >> "$FN"
done
for fn in print_action_needed is_valid_git_email is_interactive resolve_git_identity resolve_user_name; do
    if ! grep -q "${fn}()" "$FN"; then
        echo "FAIL: could not extract $fn from $SETUP"
        exit 1
    fi
done
# shellcheck disable=SC1090
source "$FN"

assert() { # assert <label> <expected> <actual>
    if [ "$2" = "$3" ]; then
        echo "  PASS: $1"
    else
        echo "  FAIL: $1 (expected '$2', got '$3')"
        FAILURES=$((FAILURES + 1))
    fi
}

# --- Stub git: read from / write to a fake config file, log every call,
# never touch the real global config. `git config --global <key>` (3 args)
# is a read; `git config --global <key> <value>` (4 args) is a write. ---
GIT_LOG="$TMP/git_calls.log"
FAKE_GLOBAL="$TMP/fake_global_config"
: > "$GIT_LOG"
: > "$FAKE_GLOBAL"
git() {
    echo "git $*" >> "$GIT_LOG"
    if [ "$1 $2" = "config --global" ]; then
        if [ "$#" -ge 4 ]; then
            grep -v "^$3=" "$FAKE_GLOBAL" > "$FAKE_GLOBAL.tmp" 2>/dev/null || true
            mv "$FAKE_GLOBAL.tmp" "$FAKE_GLOBAL"
            echo "$3=$4" >> "$FAKE_GLOBAL"
            return 0
        fi
        grep "^$3=" "$FAKE_GLOBAL" 2>/dev/null | tail -1 | cut -d= -f2-
        return 0
    fi
    return 1
}

# ============================================================
# is_valid_git_email
# ============================================================
is_valid_git_email "tom@example.com" && r=pass || r=fail
assert "valid email accepted" "pass" "$r"

is_valid_git_email "skip" && r=pass || r=fail
assert "literal 'skip' rejected as email" "fail" "$r"

is_valid_git_email "notanemail" && r=pass || r=fail
assert "no @ rejected" "fail" "$r"

is_valid_git_email "tom@nodot" && r=pass || r=fail
assert "no dot in domain rejected" "fail" "$r"

is_valid_git_email "tom smith@example.com" && r=pass || r=fail
assert "whitespace rejected" "fail" "$r"

# ============================================================
# print_action_needed
# ============================================================
ACTION_NEEDED=()
out="$(print_action_needed)"
assert "empty ACTION_NEEDED prints nothing" "" "$out"

ACTION_NEEDED=("srt missing — run: sudo npm install -g srt" "rg missing — run: sudo apt install ripgrep")
out="$(print_action_needed)"
echo "$out" | grep -q "srt missing" && r1=pass || r1=fail
echo "$out" | grep -q "rg missing" && r2=pass || r2=fail
assert "populated ACTION_NEEDED renders item 1" "pass" "$r1"
assert "populated ACTION_NEEDED renders item 2" "pass" "$r2"

# ============================================================
# resolve_git_identity — already-configured identity is left alone
# ============================================================
echo "user.email=pre@existing.com" > "$FAKE_GLOBAL"
echo "user.name=Pre Existing" >> "$FAKE_GLOBAL"
: > "$GIT_LOG"
ACTION_NEEDED=()
resolve_git_identity
assert "already-configured: GIT_EMAIL passed through" "pre@existing.com" "$GIT_EMAIL"
assert "already-configured: GIT_NAME passed through" "Pre Existing" "$GIT_NAME"
assert "already-configured: not marked skipped" "no" "$GIT_IDENTITY_SKIPPED"
assert "already-configured: no config --global writes" "" "$(grep -E '^git config --global user\.(email|name) ' "$GIT_LOG" || true)"
assert "already-configured: no ACTION_NEEDED item" "0" "${#ACTION_NEEDED[@]}"

# ============================================================
# resolve_git_identity — non-interactive, unconfigured: skip cleanly
# ============================================================
: > "$FAKE_GLOBAL"
: > "$GIT_LOG"
ACTION_NEEDED=()
is_interactive() { return 1; }
resolve_git_identity
assert "non-interactive: GIT_EMAIL stays empty" "" "$GIT_EMAIL"
assert "non-interactive: GIT_NAME stays empty" "" "$GIT_NAME"
assert "non-interactive: marked skipped" "yes" "$GIT_IDENTITY_SKIPPED"
assert "non-interactive: no config --global writes" "" "$(grep -E '^git config --global user\.(email|name) ' "$GIT_LOG" || true)"
assert "non-interactive: ACTION_NEEDED item added" "1" "${#ACTION_NEEDED[@]}"

# ============================================================
# resolve_git_identity — interactive, unconfigured: garbage rejected,
# skip word takes the clean-skip path, nothing junk gets stored.
# ============================================================
: > "$FAKE_GLOBAL"
: > "$GIT_LOG"
ACTION_NEEDED=()
is_interactive() { return 0; }
resolve_git_identity < <(printf 'skip\n')
assert "interactive skip: GIT_EMAIL stays empty" "" "$GIT_EMAIL"
assert "interactive skip: marked skipped" "yes" "$GIT_IDENTITY_SKIPPED"
assert "interactive skip: no config --global writes" "" "$(grep -E '^git config --global user\.(email|name) ' "$GIT_LOG" || true)"
assert "interactive skip: ACTION_NEEDED item added" "1" "${#ACTION_NEEDED[@]}"

# ============================================================
# resolve_git_identity — interactive, unconfigured: garbage email
# re-prompts, then a valid email + name are stored for real.
# ============================================================
: > "$FAKE_GLOBAL"
: > "$GIT_LOG"
ACTION_NEEDED=()
is_interactive() { return 0; }
resolve_git_identity < <(printf 'not-an-email\ntom@example.com\ntom\n')
assert "interactive valid: GIT_EMAIL stored" "tom@example.com" "$GIT_EMAIL"
assert "interactive valid: GIT_NAME stored" "tom" "$GIT_NAME"
assert "interactive valid: not marked skipped" "no" "$GIT_IDENTITY_SKIPPED"
assert "interactive valid: real email written to git config" "user.email=tom@example.com" "$(grep '^user.email=' "$FAKE_GLOBAL")"
assert "interactive valid: garbage email never written to git config" "" "$(grep 'not-an-email' "$FAKE_GLOBAL" || true)"
assert "interactive valid: no ACTION_NEEDED item" "0" "${#ACTION_NEEDED[@]}"

# ============================================================
# resolve_user_name
# ============================================================
unset -f is_interactive
is_interactive() { return 0; }

GIT_NAME="tom"
resolve_user_name < <(printf '\n')
assert "blank input defaults to GIT_NAME" "tom" "$USER_NAME"

GIT_NAME="tom"
resolve_user_name < <(printf 'skip\n')
assert "explicit skip with a GIT_NAME default clears USER_NAME" "" "$USER_NAME"

GIT_NAME="tom"
resolve_user_name < <(printf 'Tommy\n')
assert "custom name overrides the GIT_NAME default" "Tommy" "$USER_NAME"

GIT_NAME=""
resolve_user_name < <(printf 'Patrick\n')
assert "no GIT_NAME default: entered name is stored" "Patrick" "$USER_NAME"

GIT_NAME=""
resolve_user_name < <(printf 'skip\n')
assert "no GIT_NAME default: skip stays empty" "" "$USER_NAME"

is_interactive() { return 1; }
GIT_NAME="tom"
USER_NAME="stale"
resolve_user_name
assert "non-interactive: USER_NAME stays empty, no prompt" "" "$USER_NAME"

echo ""
if [ "$FAILURES" -eq 0 ]; then
    echo "setup_identity_test: ALL PASS"
    exit 0
fi
echo "setup_identity_test: $FAILURES FAILURE(S)"
exit 1
