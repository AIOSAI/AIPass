# Telegram Port Map (TG-MAP) — completeness manifest

> The tagged mini-map for the AS-WAS Telegram → AIPass skill port (executes **DPLAN-0208**).
> **The port is NOT "done" until every tag is PORTED and its VERIFY cell passes.** Verification (P5) audits the finished skill against this map, tag by tag — completeness is an audit, not a hope.

## How this map is used
- **STATUS lifecycle per tag:** `PENDING → PORTED → VERIFIED`. Builders mark PORTED; P5 marks VERIFIED only when the VERIFY cell is satisfied.
- **PORT ACTION legend:** `copy-as-is` · `rewire→@api` (secrets/connection) · `rewire→@prax` (logging) · `rewire→@hooks` (Stop hook) · `rewire→@cli` (Rich) · `keep(tmux/systemd)` (native equivalent stays) · `strip` (dead/Dev-Pass-only, drop) · `register` (wire into host) · `transfer` (creds move to .secrets).
- **The leak-prone rows = `SEAM` (Dev-Pass coupling) + `WART` (already-fixed bug to carry forward).** Each is individually tagged with its own VERIFY check. These are what ports silently drop — none may be skipped.

## Coverage — 366 tagged units, 5 areas
| Area | Tags | Range | Source files |
|---|---|---|---|
| CORE | 100 | TG-CORE-001..100 | base_bot.py, branch_plugin.py |
| ROUTE | 69 | TG-ROUTE-001..069 | response_router.py, telegram_standards.py, telegram_response.py (Stop hook) |
| LIFECYCLE | 69 | TG-LIFE-001..069 | bot_factory.py, bot_registry.py, bot_operations.py, botfather_client.py |
| PERIPHERAL | 86 | TG-PERIPH-001..086 | config.py, file_handler.py, log_streamer.py, notifier.py, tmux_manager.py, __init__.py |
| TESTS+INFRA | 42 | TG-TEST-001..012, TG-INFRA-001..030 | 7 test files + conftest + systemd + secrets/state + deploy prereqs |

**Secrets→@api:** 7 bot JSONs + `.telethon_config.json` + `.telethon.session` → `~/.secrets/aipass/telegram/`. **STATE stays with skill:** `{id}_offset.json`, `.{id}.lock`, `_registry.json`.

---

## CORE — TG-CORE (base_bot.py, branch_plugin.py)

| TAG | TYPE | SOURCE (file:lines) | WHAT | PORT ACTION | DEST | VERIFY |
|---|---|---|---|---|---|---|
| TG-CORE-001 | FILE | base_bot.py:1-1815 | BaseBot polling/tmux/heartbeat/lock foundation | copy-as-is | skill src/base_bot.py | file present, imports resolve, unit tests pass |
| TG-CORE-002 | FILE | branch_plugin.py:1-174 | BranchPlugin per-branch hook extension | copy-as-is | skill src/branch_plugin.py | file present, BranchPlugin importable |
| TG-CORE-003 | SEAM | base_bot.py:1 | Hardcoded venv shebang | strip | system python | grep: no /home/aipass/.venv |
| TG-CORE-004 | SEAM | branch_plugin.py:1 | Hardcoded venv shebang | strip | system python | grep: no /home/aipass/.venv |
| TG-CORE-005 | CONST | base_bot.py:59 | AIPASS_ROOT hardcoded to home/aipass_core | rewire→@api | pathlib/config | grep: no aipass_core literal |
| TG-CORE-006 | CONST | branch_plugin.py:43-44 | AIPASS_ROOT repeated + sys.path mutation | rewire→@api | proper package install | grep: no sys.path.insert |
| TG-CORE-007 | DEP | base_bot.py:81 | prax.apps.modules.logger get_direct_logger | rewire→@prax | from aipass.prax import logger | grep: no prax.apps.modules import |
| TG-CORE-008 | DEP | base_bot.py:88-105 | telegram_standards sibling import | copy-as-is | skill sibling module | /start /help /status work |
| TG-CORE-009 | DEP | base_bot.py:97-99 | file_handler sibling import | copy-as-is | skill sibling module | file upload handled |
| TG-CORE-010 | DEP | base_bot.py:101-105 | bot_factory sibling import | copy-as-is | skill sibling module | /create flow works |
| TG-CORE-011 | DEP | base_bot.py:106-109 | bot_registry sibling import | copy-as-is | skill sibling module | /status shows registry bots |
| TG-CORE-012 | DEP | base_bot.py:110-113 | botfather_client/Telethon sibling import | copy-as-is | skill sibling module | automated /create executes |
| TG-CORE-013 | DEP | base_bot.py:114 | LogStreamer sibling import | copy-as-is | skill sibling module | log streaming starts |
| TG-CORE-014 | DEP | base_bot.py:57-78 | stdlib imports (json,os,signal,subprocess,threading,time,uuid,argparse,atexit) | copy-as-is | stdlib | imports resolve, no pip |
| TG-CORE-015 | DEP | base_bot.py:76-78 | urllib.error/request | copy-as-is | stdlib | polling+sendMessage via urllib |
| TG-CORE-016 | DEP | base_bot.py:49 | argparse CLI (--bot-id, --config) | copy-as-is | skill CLI entry | python base_bot.py --bot-id x works |
| TG-CORE-017 | CONST | base_bot.py:152 | PENDING_DIR ~/.aipass/telegram_pending | copy-as-is | skill .local state dir | dir created, pending written |
| TG-CORE-018 | CONST | base_bot.py:153 | PENDING_TTL=3600 | copy-as-is | skill constant | stale pending cleaned after 1h |
| TG-CORE-019 | CONST | base_bot.py:154 | TELEGRAM_CHAR_LIMIT=4096 | copy-as-is | skill constant | long msgs chunked |
| TG-CORE-020 | CONST | base_bot.py:155 | RATE_LIMIT_MESSAGES=5 | copy-as-is | skill constant | 6th msg/60s blocked |
| TG-CORE-021 | CONST | base_bot.py:156 | RATE_LIMIT_WINDOW=60 | copy-as-is | skill constant | rate window resets |
| TG-CORE-022 | CONST | base_bot.py:157 | POLL_TIMEOUT=30 | copy-as-is | skill constant | getUpdates long-poll 30s |
| TG-CORE-023 | CONST | base_bot.py:158 | SEND_KEYS_DELAY=0.5 | copy-as-is | skill constant | 0.5s gap between send-keys |
| TG-CORE-024 | CONST | base_bot.py:159 | HEARTBEAT_INTERVAL=30 | copy-as-is | skill constant | Processing edits every 30s |
| TG-CORE-025 | CONST | base_bot.py:160 | CLAUDE_BIN ~/.local/bin/claude | keep(tmux/systemd) | pathlib/config | live: claude launched |
| TG-CORE-026 | CONST | base_bot.py:161 | TEMP_DIR /tmp/telegram_uploads | copy-as-is | skill .local / keep /tmp | uploads appear in TEMP_DIR |
| TG-CORE-027 | CONST | base_bot.py:162 | MAX_FILE_SIZE 10MB | copy-as-is | skill constant | >10MB rejected |
| TG-CORE-028 | CONFIG | base_bot.py:1795-1803 | Bot config from ~/.aipass/telegram_bots/{id}.json | rewire→@api | drone @api get-secret telegram/<id> | grep: no direct .aipass open |
| TG-CORE-029 | SECRET | base_bot.py:1807 | bot_token from config | rewire→@api | get-secret telegram/<id> | bot_token not hardcoded |
| TG-CORE-030 | SECRET | base_bot.py:1808 | allowed_user_ids from config | rewire→@api | get-secret telegram/<id> | allowed_user_ids populated runtime |
| TG-CORE-031 | STATE | base_bot.py:216-217 | pending_file bot-{id}.json | copy-as-is | skill .local state dir | written/deleted in cycle |
| TG-CORE-032 | STATE | base_bot.py:253 | _lock_file .{id}.lock | copy-as-is | skill .local state dir | lock present while running |
| TG-CORE-033 | STATE | base_bot.py:256 | _offset_file {id}_offset.json | copy-as-is | skill .local state dir | offset persists across restart |
| TG-CORE-034 | CLASS | base_bot.py:169-1783 | BaseBot — runnable+inheritable | copy-as-is | skill src/base_bot.py | importable, bot.run() returns 0 |
| TG-CORE-035 | FUNC | base_bot.py:178-256 | __init__ constructor | copy-as-is | skill | instantiates without error |
| TG-CORE-036 | FUNC | base_bot.py:262-336 | run — polling loop w/ backoff | copy-as-is | skill | loop runs, retry doubles |
| TG-CORE-037 | FUNC | base_bot.py:342-375 | verify_connection getMe | copy-as-is | skill | startup fails on bad token |
| TG-CORE-038 | FUNC | base_bot.py:377-410 | poll_updates getUpdates | copy-as-is | skill | updates received after send |
| TG-CORE-039 | FUNC | base_bot.py:412-460 | send_message 3-retry | copy-as-is | skill | message appears in chat |
| TG-CORE-040 | FUNC | base_bot.py:462-492 | edit_message editMessageText | copy-as-is | skill | Processing updates elapsed |
| TG-CORE-041 | FUNC | base_bot.py:498-637 | process_update routes cmd/file/msg | copy-as-is | skill | all routed |
| TG-CORE-042 | FUNC | base_bot.py:643-700 | handle_message tmux inject flow | copy-as-is | skill | live: msg injected, pending written |
| TG-CORE-043 | FUNC | base_bot.py:702-803 | handle_file photo/doc download+inject | copy-as-is | skill | file forwarded to Claude |
| TG-CORE-044 | FUNC | base_bot.py:805-871 | _download_file getFile+urllib | copy-as-is | skill | file in TEMP_DIR |
| TG-CORE-045 | FUNC | base_bot.py:877-950 | _handle_create_command /create routing | copy-as-is | skill | /create chat triggers flow |
| TG-CORE-046 | FUNC | base_bot.py:952-1033 | _handle_create_automated Telethon | copy-as-is | skill | bot created, systemd started |
| TG-CORE-047 | FUNC | base_bot.py:1035-1114 | _handle_create_token manual step2 | copy-as-is | skill | token validated, factory called |
| TG-CORE-048 | FUNC | base_bot.py:1116-1139 | _build_registry_status /status info | copy-as-is | skill | /status lists bots |
| TG-CORE-049 | FUNC | base_bot.py:1145-1206 | chunk_text smart split | copy-as-is | skill | >4096 split at sentence |
| TG-CORE-050 | FUNC | base_bot.py:1212-1224 | is_user_allowed allowlist | copy-as-is | skill | blocked user no response |
| TG-CORE-051 | FUNC | base_bot.py:1226-1252 | check_rate_limit sliding window | copy-as-is | skill | 6th msg blocked |
| TG-CORE-052 | FUNC | base_bot.py:1258-1365 | ensure_tmux_session create/attach+Claude | keep(tmux/systemd) | skill | live: session created, claude running |
| TG-CORE-053 | FUNC | base_bot.py:1367-1399 | inject_message tmux send-keys literal | keep(tmux/systemd) | skill | live: msg injected |
| TG-CORE-054 | FUNC | base_bot.py:1401-1410 | _tmux_session_exists has-session | keep(tmux/systemd) | skill | True when session live |
| TG-CORE-055 | FUNC | base_bot.py:1412-1444 | _kill_tmux_session kill+guard shared | keep(tmux/systemd) | skill | /new kills own, shared protected |
| TG-CORE-056 | FUNC | base_bot.py:1450-1489 | write_pending_file JSON for Stop hook | copy-as-is | skill .local state dir | pending exists after handle_message |
| TG-CORE-057 | FUNC | base_bot.py:1491-1501 | clean_stale_pending remove expired | copy-as-is | skill | stale removed on restart |
| TG-CORE-058 | FUNC | base_bot.py:1503-1526 | _get_transcript_line_count position track | copy-as-is | skill | transcript_line_after set |
| TG-CORE-059 | FUNC | base_bot.py:1532-1566 | _start_heartbeat daemon edits Processing | copy-as-is | skill | Processing updates 30s |
| TG-CORE-060 | FUNC | base_bot.py:1568-1573 | _stop_heartbeat signal+join | copy-as-is | skill | thread exits within 5s |
| TG-CORE-061 | FUNC | base_bot.py:1575-1590 | _format_elapsed static formatter | copy-as-is | skill | "30s","1m 0s" correct |
| TG-CORE-062 | FUNC | base_bot.py:1596-1608 | on_message hook passthrough | copy-as-is | skill | override changes prompt |
| TG-CORE-063 | FUNC | base_bot.py:1610-1622 | on_response hook passthrough | copy-as-is | skill | override modifies response |
| TG-CORE-064 | FUNC | base_bot.py:1624-1635 | on_session_create hook no-op | copy-as-is | skill | BranchPlugin injects "hi" |
| TG-CORE-065 | FUNC | base_bot.py:1637-1656 | get_custom_commands /create+/cancel | copy-as-is | skill | /help shows /create /cancel |
| TG-CORE-066 | FUNC | base_bot.py:1662-1677 | _create_lock write PID JSON | copy-as-is | skill .local state dir | lock contains current PID |
| TG-CORE-067 | FUNC | base_bot.py:1679-1686 | _remove_lock delete on exit | copy-as-is | skill .local state dir | lock absent after shutdown |
| TG-CORE-068 | FUNC | base_bot.py:1688-1735 | _check_lock PID liveness+/proc cmdline identity | copy-as-is | skill | live: lock survives PID reuse |
| TG-CORE-069 | FUNC | base_bot.py:1741-1747 | _shutdown_handler SIGTERM/SIGINT | copy-as-is | skill | SIGTERM stops loop cleanly |
| TG-CORE-070 | FUNC | base_bot.py:1749-1756 | _cleanup atexit stop streamer/heartbeat/lock | copy-as-is | skill | lock removed, streamer stopped |
| TG-CORE-071 | FUNC | base_bot.py:1762-1770 | _load_offset read offset JSON | copy-as-is | skill .local state dir | offset loaded on restart |
| TG-CORE-072 | FUNC | base_bot.py:1773-1782 | _save_offset persist after update | copy-as-is | skill .local state dir | offset updated after poll |
| TG-CORE-073 | CLASS | branch_plugin.py:65-128 | BranchPlugin per-branch overrides | copy-as-is | skill src/branch_plugin.py | importable, inherits BaseBot |
| TG-CORE-074 | FUNC | branch_plugin.py:73-82 | __init__ stores branch_name+super | copy-as-is | skill | works |
| TG-CORE-075 | FUNC | branch_plugin.py:88-98 | on_message prefix "Patrick via Telegram: " | copy-as-is | skill | injected prompt has prefix |
| TG-CORE-076 | FUNC | branch_plugin.py:100-110 | on_response prefix "@{branch}\n" | copy-as-is | skill | reply starts with @branch |
| TG-CORE-077 | FUNC | branch_plugin.py:112-128 | on_session_create inject "hi" after 2s | keep(tmux/systemd) | skill | live: "hi" injected 2s after session |
| TG-CORE-078 | SEAM | base_bot.py:1300-1305 | work_dir.is_dir() guard before tmux | copy-as-is | skill | bad work_dir returns False |
| TG-CORE-079 | SEAM | base_bot.py:1312-1314 | env.pop CLAUDECODE before tmux | keep(tmux/systemd) | skill | grep: CLAUDECODE stripped |
| TG-CORE-080 | SEAM | base_bot.py:1338 | --permission-mode bypassPermissions flag | keep(tmux/systemd) | skill | claude launched w/ flag |
| TG-CORE-081 | SEAM | base_bot.py:1510 | slug=work_dir.replace('/','-') transcript path | copy-as-is | skill | transcript uses slug |
| TG-CORE-082 | SEAM | base_bot.py:1716-1728 | PID identity via /proc/{pid}/cmdline | copy-as-is | skill | live: lock survives PID reuse |
| TG-CORE-083 | SEAM | base_bot.py:219 | shared_session attaches existing tmux | keep(tmux/systemd) | skill | shared injected, fallback own |
| TG-CORE-084 | SEAM | base_bot.py:1413-1422 | _kill_tmux protects shared from /new | keep(tmux/systemd) | skill | /new on shared detaches |
| TG-CORE-085 | SEAM | base_bot.py:211-213 | branch_name set-before-super init order | copy-as-is | skill | branch_name not overwritten |
| TG-CORE-086 | SEAM | base_bot.py:244-247 | LogStreamer lazy start on first message | copy-as-is | skill | streamer absent until 1st msg |
| TG-CORE-087 | WART | base_bot.py:1718-1728 | /proc cmdline fix prevents stale lock PID reuse | copy-as-is | skill | live: lock survives PID reuse |
| TG-CORE-088 | WART | base_bot.py:1300-1305 | work_dir guard prevents tmux $HOME fallback | copy-as-is | skill | bad work_dir logs error |
| TG-CORE-089 | WART | base_bot.py:1312-1314 | CLAUDECODE strip prevents "cannot run inside Claude" | keep(tmux/systemd) | skill | session w/o CLAUDECODE error |
| TG-CORE-090 | WART | base_bot.py:1338 | bypassPermissions required for unattended Claude | keep(tmux/systemd) | skill | Claude starts no prompt |
| TG-CORE-091 | STATE | base_bot.py:222-227 | self.state running/count/start/last | copy-as-is | skill instance state | /status correct counts |
| TG-CORE-092 | STATE | base_bot.py:229-235 | self._health started/recv/fail/errors | copy-as-is | skill instance state | health populated after 1st msg |
| TG-CORE-093 | STATE | base_bot.py:237 | _rate_limit_tracker per user_id | copy-as-is | skill instance state | resets between restarts |
| TG-CORE-094 | STATE | base_bot.py:241-242 | _create_state /create flow state | copy-as-is | skill instance state | /cancel clears state |
| TG-CORE-095 | STATE | base_bot.py:246-247 | _log_streamer/_active_chat_id lazy | copy-as-is | skill instance state | streamer starts once |
| TG-CORE-096 | CONFIG | base_bot.py:146-147 | Config path ~/.aipass/telegram_bots/{id}.json | rewire→@api | get-secret telegram/<id> | grep: no direct .aipass open |
| TG-CORE-097 | CONFIG | branch_plugin.py:141-148 | Same config path in CLI entry | rewire→@api | get-secret telegram/<id> | grep: no direct .aipass open |
| TG-CORE-098 | CONFIG | branch_plugin.py:152 | shared_session from config | rewire→@api | get-secret telegram/<id> | shared_session passed in |
| TG-CORE-099 | SEAM | base_bot.py:1511-1513 | Transcript dir ~/.claude/projects/{slug}/*.jsonl | copy-as-is | skill | transcript_line_after correct |
| TG-CORE-100 | DEP | base_bot.py:1327-1334 | AIPASS_BOT_ID env exported into tmux | keep(tmux/systemd) | skill | tmux env has AIPASS_BOT_ID |

## ROUTE — TG-ROUTE (response_router.py, telegram_standards.py, telegram_response.py Stop hook)

| TAG | TYPE | SOURCE (file:lines) | WHAT | PORT ACTION | DEST | VERIFY |
|---|---|---|---|---|---|---|
| TG-ROUTE-001 | FILE | response_router.py:1-341 | CWD-safe pending-file routing multi-bot | copy-as-is | skill | file present |
| TG-ROUTE-002 | DEP | response_router.py:51 | prax system_logger import | rewire→@prax | skill | logger emits, no ImportError |
| TG-ROUTE-003 | CONST | response_router.py:57 | PENDING_DIR ~/.aipass/telegram_pending | copy-as-is | skill | path matches writes |
| TG-ROUTE-004 | CONST | response_router.py:58 | PENDING_TTL=3600 | copy-as-is | skill | expired at 3601s |
| TG-ROUTE-005 | FUNC | response_router.py:66-85 | is_cwd_in_tree relative_to check | copy-as-is | skill | subdir returns True |
| TG-ROUTE-006 | FUNC | response_router.py:93-113 | is_tmux_alive subprocess check | keep(tmux/systemd) | skill | live: session detected |
| TG-ROUTE-007 | FUNC | response_router.py:120-163 | is_pending_expired TTL+tmux dual | copy-as-is | skill | TTL+dead returns True |
| TG-ROUTE-008 | WART | response_router.py:150-163 | TTL expiry needs age>TTL AND tmux dead | copy-as-is | skill | alive tmux blocks expiry |
| TG-ROUTE-009 | FUNC | response_router.py:171-188 | _load_pending_file JSON+key inject | copy-as-is | skill | bad JSON returns None |
| TG-ROUTE-010 | FUNC | response_router.py:196-295 | find_pending_bot 3-priority match | copy-as-is | skill | all 3 paths hit |
| TG-ROUTE-011 | SEAM | response_router.py:233 | AIPASS_BOT_ID env Priority-1 | copy-as-is | skill | live: env var resolves |
| TG-ROUTE-012 | SEAM | response_router.py:238 | Pending naming v2 bot-{id}.json | copy-as-is | skill | glob matches written |
| TG-ROUTE-013 | SEAM | response_router.py:246 | Pending naming v1 legacy telegram-{id}.json | copy-as-is | skill | v1 still resolved |
| TG-ROUTE-014 | SEAM | response_router.py:255 | Glob both bot-*+telegram-* | copy-as-is | skill | both globs return |
| TG-ROUTE-015 | WART | response_router.py:271-279 | v1 no work_dir: walk CWD parents for branch | copy-as-is | skill | parent dir matches branch |
| TG-ROUTE-016 | FUNC | response_router.py:303-341 | clean_expired_pending remove stale | copy-as-is | skill | count==removed |
| TG-ROUTE-017 | WART | response_router.py:322-327 | Corrupt pending auto-removed on load fail | copy-as-is | skill | corrupt file deleted |
| TG-ROUTE-018 | FILE | telegram_standards.py:1-372 | Shared stdlib standards all bots | copy-as-is | skill | no import errors |
| TG-ROUTE-019 | CONST | telegram_standards.py:52-69 | STANDARD_COMMANDS start/help/new/status | copy-as-is | skill | all 4 handled |
| TG-ROUTE-020 | CONST | telegram_standards.py:76 | PROCESSING_MSG "Processing..." | copy-as-is | skill | text matches |
| TG-ROUTE-021 | CONST | telegram_standards.py:78 | ERROR_TEMPLATE | copy-as-is | skill | error replies use template |
| TG-ROUTE-022 | CONST | telegram_standards.py:80 | HELP_FOOTER | copy-as-is | skill | help has footer |
| TG-ROUTE-023 | FUNC | telegram_standards.py:93-115 | _format_command_list formatter | copy-as-is | skill | custom cmds appended |
| TG-ROUTE-024 | FUNC | telegram_standards.py:118-140 | build_help_text /help builder | copy-as-is | skill | /help has all commands |
| TG-ROUTE-025 | FUNC | telegram_standards.py:143-172 | build_welcome_text /start builder | copy-as-is | skill | /start has bot_name+branch |
| TG-ROUTE-026 | FUNC | telegram_standards.py:175-211 | build_status_text /status builder | keep(tmux/systemd) | skill | /status Active/Inactive via tmux |
| TG-ROUTE-027 | FUNC | telegram_standards.py:214-240 | build_botfather_commands API list | copy-as-is | skill | matches setMyCommands |
| TG-ROUTE-028 | FUNC | telegram_standards.py:247-284 | parse_command extract+strip @botname | copy-as-is | skill | /cmd@bot + /cmd args parsed |
| TG-ROUTE-029 | FUNC | telegram_standards.py:287-346 | handle_standard_command dispatch | copy-as-is | skill | all 4 return expected type |
| TG-ROUTE-030 | WART | telegram_standards.py:333-335 | /new returns tuple not str — caller acts | copy-as-is | skill | caller checks tuple |
| TG-ROUTE-031 | FUNC | telegram_standards.py:353-371 | _tmux_session_exists internal check | keep(tmux/systemd) | skill | live: True for running |
| TG-ROUTE-032 | DEP | telegram_standards.py:44 | subprocess for tmux check | keep(tmux/systemd) | skill | subprocess.run succeeds |
| TG-ROUTE-033 | FILE | telegram_response.py:1-621 | Stop hook: read transcript, send reply | rewire→@hooks | skill | hook registered+fires |
| TG-ROUTE-034 | SEAM | telegram_response.py:619 + settings.json | Hook registration in settings.json | rewire→@hooks | skill | hook entry, fires on Stop |
| TG-ROUTE-035 | CONFIG | telegram_response.py:59-60 | LOG_FILE ~/system_logs/telegram_hook.log | copy-as-is | skill | log created, entries written |
| TG-ROUTE-036 | CONST | telegram_response.py:70 | PENDING_DIR ~/.aipass/telegram_pending | copy-as-is | skill | matches router+BaseBot path |
| TG-ROUTE-037 | CONST | telegram_response.py:71 | PENDING_TTL=3600 | copy-as-is | skill | consistent w/ router |
| TG-ROUTE-038 | CONST | telegram_response.py:72 | TELEGRAM_CHAR_LIMIT=4096 | copy-as-is | skill | chunk at 4096 |
| TG-ROUTE-039 | FUNC | telegram_response.py:75-98 | _is_expired local TTL+tmux check | copy-as-is | skill | mirrors router expiry |
| TG-ROUTE-040 | FUNC | telegram_response.py:101-150 | find_pending_file v2 2-priority | copy-as-is | skill | env+cwd paths hit |
| TG-ROUTE-041 | WART | telegram_response.py:101 | session_id param kept compat, unused | copy-as-is | skill | param present, no logic |
| TG-ROUTE-042 | FUNC | telegram_response.py:153-240 | extract_assistant_response JSONL parse | copy-as-is | skill | returns joined blocks |
| TG-ROUTE-043 | SEAM | telegram_response.py:153 | transcript ~/.claude/projects/{slug}/*.jsonl | register | config | slug→path config |
| TG-ROUTE-044 | SEAM | telegram_response.py:153 | slug=work_dir.replace('/','-') CC coupling | register | config | slug tested vs real paths |
| TG-ROUTE-045 | WART | telegram_response.py:182-205 | Layer2: skip isSidechain=True | copy-as-is | skill | sidechain filtered |
| TG-ROUTE-046 | WART | telegram_response.py:196-204 | Skip tool_result "user" intermediate msgs | copy-as-is | skill | tool_result skipped |
| TG-ROUTE-047 | WART | telegram_response.py:531 | Layer3 cursor transcript_line_after | STATE | skill | cursor matches bridge value |
| TG-ROUTE-048 | WART | telegram_response.py:533-542 | JSONL flush-race 3 retries 200/500ms | copy-as-is | skill | 3rd attempt succeeds |
| TG-ROUTE-049 | WART | telegram_response.py:545-548 | last_assistant_message stdin fallback | copy-as-is | skill | fallback used when JSONL empty |
| TG-ROUTE-050 | WART | telegram_response.py:484-489 | Layer1: reject SubagentStop event | copy-as-is | skill | live: subagent-stop filtered |
| TG-ROUTE-051 | WART | telegram_response.py:494-496 | Layer1b: reject /subagents/ paths | copy-as-is | skill | subagent path early return |
| TG-ROUTE-052 | WART | telegram_response.py:554-559 | @branch prefix via Path.cwd().name | copy-as-is | skill | live: reply prefixed |
| TG-ROUTE-053 | WART | telegram_response.py:562-573 | Wait 7s if log_streamer active | copy-as-is | skill | live: reply after flush |
| TG-ROUTE-054 | STATE | telegram_response.py:510-513 | Read+delete pending after delivery | copy-as-is | skill | live: pending absent after send |
| TG-ROUTE-055 | FUNC | telegram_response.py:243-299 | chunk_text smart split | copy-as-is | skill | chunks<=4096 |
| TG-ROUTE-056 | FUNC | telegram_response.py:302-349 | markdown_to_telegram_html | copy-as-is | skill | code/bold/italic rendered |
| TG-ROUTE-057 | WART | telegram_response.py:315-318 | Placeholder protect code blocks pre-escape | copy-as-is | skill | md inside code untouched |
| TG-ROUTE-058 | FUNC | telegram_response.py:352-415 | send_to_telegram urllib send | copy-as-is | skill | live: reply delivered |
| TG-ROUTE-059 | WART | telegram_response.py:368-381 | HTML first, plain-text fallback | copy-as-is | skill | live: HTML ok, fallback mocked |
| TG-ROUTE-060 | FUNC | telegram_response.py:418-463 | edit_telegram_message edit API | copy-as-is | skill | live: Processing replaced |
| TG-ROUTE-061 | FUNC | telegram_response.py:466-620 | main() Stop hook entry, reads stdin | rewire→@hooks | skill | hook fires, main() called |
| TG-ROUTE-062 | SEAM | telegram_response.py:479-482 | json.load(sys.stdin) hook payload | copy-as-is | skill | stdin parsed, missing→silent exit |
| TG-ROUTE-063 | STATE | telegram_response.py:516-518 | chat_id+bot_token from pending | STATE | skill | missing→clean abort+delete |
| TG-ROUTE-064 | SECRET | telegram_response.py:517 | bot_token in pending (runtime secret) | copy-as-is | skill | token not logged, pending deleted |
| TG-ROUTE-065 | FUNC | telegram_response.py:579-588 | send_with_retry closure backoff | copy-as-is | skill | 3 attempts 1s/2s |
| TG-ROUTE-066 | WART | telegram_response.py:592-609 | Edit Processing for 1st chunk; new msg if logs active | copy-as-is | skill | live: correct message order |
| TG-ROUTE-067 | WART | telegram_response.py:611-616 | Failed delivery keeps pending for retry | copy-as-is | skill | live: retry on next Stop |
| TG-ROUTE-068 | DEP | telegram_response.py:55-56 | urllib (stdlib) | copy-as-is | skill | stdlib only |
| TG-ROUTE-069 | DEP | telegram_response.py:49 | re module markdown regex | copy-as-is | skill | regex compile+match |

## LIFECYCLE — TG-LIFE (bot_factory.py, bot_registry.py, bot_operations.py, botfather_client.py)

| TAG | TYPE | SOURCE (file:lines) | WHAT | PORT ACTION | DEST | VERIFY |
|---|---|---|---|---|---|---|
| TG-LIFE-001 | FILE | bot_factory.py:1-539 | Bot create/delete orchestrator | copy-as-is | skill/telegram | file present |
| TG-LIFE-002 | FILE | bot_registry.py:1-367 | fcntl-locked _registry.json CRUD | copy-as-is | skill/telegram | registry ops work |
| TG-LIFE-003 | FILE | bot_operations.py:1-244 | start/stop/status ops, no logging | copy-as-is | skill/telegram | file present |
| TG-LIFE-004 | FILE | botfather_client.py:1-535 | Telethon BotFather automation | copy-as-is | skill/telegram | file present |
| TG-LIFE-005 | DEP | bot_factory.py:50 | prax system_logger | rewire→@prax | @prax | logger emits |
| TG-LIFE-006 | DEP | bot_registry.py:45 | prax system_logger | rewire→@prax | @prax | logger emits |
| TG-LIFE-007 | DEP | botfather_client.py:54 | prax system_logger | rewire→@prax | @prax | logger emits |
| TG-LIFE-008 | DEP | botfather_client.py:57-63 | telethon optional guarded import | register | skill deps | TELETHON_AVAILABLE guard present |
| TG-LIFE-009 | CONST | bot_factory.py:61 | TELEGRAM_API URL template | copy-as-is | skill/telegram | constant present |
| TG-LIFE-010 | CONST | bot_factory.py:62 | BOT_CONFIG_DIR ~/.aipass/telegram_bots | copy-as-is | skill/telegram | dir created on create |
| TG-LIFE-011 | CONST | bot_factory.py:63 | BRANCH_REGISTRY ~/BRANCH_REGISTRY.json | strip | AIPass registry/config | reads AIPass registry |
| TG-LIFE-012 | CONST | bot_factory.py:64 | SYSTEMD_DIR ~/.config/systemd/user | keep(tmux/systemd) | skill/telegram | systemctl --user works |
| TG-LIFE-013 | CONST | bot_factory.py:67-72 | DEFAULT_BOT_COMMANDS for setMyCommands | copy-as-is | skill/telegram | commands set on new bot |
| TG-LIFE-014 | CONST | bot_registry.py:51-52 | REGISTRY_DIR+REGISTRY_FILE | copy-as-is | STATE | _registry.json created |
| TG-LIFE-015 | CONST | botfather_client.py:69-70 | BOT_CONFIG_DIR+TELETHON_CONFIG_PATH | rewire→@api | @api | config via @api secret |
| TG-LIFE-016 | CONST | botfather_client.py:71 | SESSION_PATH .telethon session | rewire→@api | @api | session path from @api |
| TG-LIFE-017 | CONST | botfather_client.py:73 | BOTFATHER_USERNAME "BotFather" | copy-as-is | skill/telegram | entity resolved |
| TG-LIFE-018 | CONST | botfather_client.py:74 | BOT_TOKEN_PATTERN regex | copy-as-is | skill/telegram | regex extracts token |
| TG-LIFE-019 | CONST | botfather_client.py:77 | MESSAGE_TIMEOUT 30s | copy-as-is | skill/telegram | timeout logged on expiry |
| TG-LIFE-020 | CONST | botfather_client.py:78 | MAX_USERNAME_ATTEMPTS 3 | copy-as-is | skill/telegram | 3 attempts before fail |
| TG-LIFE-021 | SECRET | bot_factory.py:410-418 | bot_token written to config JSON | rewire→@api | @api | token via get-secret |
| TG-LIFE-022 | SECRET | botfather_client.py:86-120 | .telethon_config api_id+api_hash | rewire→@api | @api | creds via get-secret |
| TG-LIFE-023 | CONFIG | bot_factory.py:410-418 | per-bot config id/name/branch/work_dir | rewire→@api | @api | config bundled w/ secret |
| TG-LIFE-024 | STATE | bot_registry.py:51-52 | _registry.json active bots | copy-as-is | skill/telegram | CRUD passes |
| TG-LIFE-025 | FUNC | bot_factory.py:79-113 | validate_token getMe check | rewire→@api | @api | token validated |
| TG-LIFE-026 | FUNC | bot_factory.py:116-148 | validate_branch BRANCH_REGISTRY lookup | strip | AIPass registry/config | validated vs AIPass registry |
| TG-LIFE-027 | FUNC | bot_factory.py:151-182 | set_bot_commands setMyCommands | copy-as-is | skill/telegram | commands set, ok=true |
| TG-LIFE-028 | FUNC | bot_factory.py:190-222 | enable_service systemctl enable | keep(tmux/systemd) | skill/telegram | enable returns 0 |
| TG-LIFE-029 | FUNC | bot_factory.py:225-257 | disable_service systemctl disable | keep(tmux/systemd) | skill/telegram | disable returns 0 |
| TG-LIFE-030 | FUNC | bot_factory.py:260-288 | start_bot_process Popen base_bot fire-forget | keep(tmux/systemd) | skill/telegram | pid logged on start |
| TG-LIFE-031 | FUNC | bot_factory.py:291-323 | stop_service systemctl stop | keep(tmux/systemd) | skill/telegram | stop returns 0 |
| TG-LIFE-032 | FUNC | bot_factory.py:331-467 | create_bot 8-step lifecycle | copy-as-is | skill/telegram | bot registered+enabled |
| TG-LIFE-033 | FUNC | bot_factory.py:470-539 | delete_bot stop/disable/kill/deregister | copy-as-is | skill/telegram | bot absent after |
| TG-LIFE-034 | FUNC | bot_registry.py:80-98 | ensure_registry mkdir+init | copy-as-is | skill/telegram | _registry.json exists |
| TG-LIFE-035 | FUNC | bot_registry.py:106-132 | load_registry fcntl LOCK_SH | copy-as-is | skill/telegram | returns dict w/ bots |
| TG-LIFE-036 | FUNC | bot_registry.py:135-164 | save_registry fcntl LOCK_EX+timestamp | copy-as-is | skill/telegram | file updated |
| TG-LIFE-037 | FUNC | bot_registry.py:172-183 | get_bot lookup by id | copy-as-is | skill/telegram | returns entry/None |
| TG-LIFE-038 | FUNC | bot_registry.py:186-202 | list_bots optional status filter | copy-as-is | skill/telegram | returns list |
| TG-LIFE-039 | FUNC | bot_registry.py:205-257 | register_bot add+service_name | copy-as-is | skill/telegram | bot_id present after |
| TG-LIFE-040 | FUNC | bot_registry.py:260-290 | update_bot kwargs patch+stamp | copy-as-is | skill/telegram | field updated |
| TG-LIFE-041 | FUNC | bot_registry.py:293-317 | deregister_bot delete entry | copy-as-is | skill/telegram | bot_id absent |
| TG-LIFE-042 | FUNC | bot_registry.py:325-339 | get_bot_by_branch | copy-as-is | skill/telegram | returns entry/None |
| TG-LIFE-043 | FUNC | bot_registry.py:342-366 | get_bot_by_work_dir match CWD | copy-as-is | skill/telegram | router resolves bot |
| TG-LIFE-044 | FUNC | bot_operations.py:54-99 | start_bot load config, dispatch Base/Branch | copy-as-is | skill/telegram | correct type run() |
| TG-LIFE-045 | FUNC | bot_operations.py:102-130 | stop_bot systemctl wrapper | keep(tmux/systemd) | skill/telegram | True+msg on success |
| TG-LIFE-046 | FUNC | bot_operations.py:133-147 | get_status registry one/all | copy-as-is | skill/telegram | returns list |
| TG-LIFE-047 | FUNC | bot_operations.py:150-157 | get_all_bots wrapper | copy-as-is | skill/telegram | returns all entries |
| TG-LIFE-048 | FUNC | bot_operations.py:160-184 | format_bot_details display lines | copy-as-is | skill/telegram | 6-line output |
| TG-LIFE-049 | FUNC | bot_operations.py:187-209 | format_bot_table renderer | copy-as-is | skill/telegram | header+rows+total |
| TG-LIFE-050 | FUNC | bot_operations.py:212-243 | parse_create_args CLI parser | copy-as-is | skill/telegram | returns id+token dict |
| TG-LIFE-051 | CLASS | botfather_client.py:209-454 | BotFatherClient async Telethon driver | copy-as-is | skill/telegram | importable, guarded |
| TG-LIFE-052 | FUNC | botfather_client.py:227-268 | connect load session, assert authed | rewire→@api | @api | session from @api |
| TG-LIFE-053 | FUNC | botfather_client.py:270-279 | disconnect teardown | copy-as-is | skill/telegram | client None after |
| TG-LIFE-054 | FUNC | botfather_client.py:281-351 | _send_and_wait FloodWait retry+poll | copy-as-is | skill/telegram | response or None |
| TG-LIFE-055 | FUNC | botfather_client.py:353-454 | create_bot async /newbot flow | copy-as-is | skill/telegram | returns token+username |
| TG-LIFE-056 | FUNC | botfather_client.py:462-534 | create_bot_via_botfather sync wrapper | copy-as-is | skill/telegram | callable non-async |
| TG-LIFE-057 | FUNC | botfather_client.py:128-156 | check_telethon_setup lib+config+session | copy-as-is | skill/telegram | (True,"ready") when set |
| TG-LIFE-058 | SEAM | bot_factory.py:377-385 | work_dir source-of-truth=registry not arg | copy-as-is | skill/telegram | registry overrides arg |
| TG-LIFE-059 | SEAM | bot_factory.py:63 | BRANCH_REGISTRY Dev-Pass-specific | strip | AIPass registry/config | AIPass registry replaces |
| TG-LIFE-060 | SEAM | bot_operations.py:44 | start_bot imports BaseBot+BranchPlugin dispatch | copy-as-is | skill/telegram | correct class by branch |
| TG-LIFE-061 | SEAM | bot_registry.py:239 | service_name=telegram-bot@{id} | keep(tmux/systemd) | skill/telegram | service_name in entry |
| TG-LIFE-062 | SEAM | botfather_client.py:506-519 | asyncio nested-loop ThreadPoolExecutor fallback | copy-as-is | skill/telegram | no RuntimeError |
| TG-LIFE-063 | WART | bot_factory.py:260-288 | start_bot_process launches base_bot NOT branch_plugin | copy-as-is | skill/telegram | Popen target=base_bot.py |
| TG-LIFE-064 | WART | bot_factory.py:377-385 | explicit work_dir silently overridden by registry | copy-as-is | skill/telegram | warning logged |
| TG-LIFE-065 | WART | bot_factory.py:520-531 | delete_bot cleans v1+v2 pending naming | copy-as-is | skill/telegram | both files removed |
| TG-LIFE-066 | WART | botfather_client.py:77-78 | BotFather 30s timeout, 3 username retries (rate-limit risk) | copy-as-is | skill/telegram | fail logged after 3 |
| TG-LIFE-067 | WART | botfather_client.py:413-441 | username-taken by keyword in reply | copy-as-is | skill/telegram | sorry/already/taken matched |
| TG-LIFE-068 | WART | bot_registry.py:124-126 | corrupt registry silently returns empty | copy-as-is | skill/telegram | warning logged, empty dict |
| TG-LIFE-069 | WART | bot_registry.py:211 | bot_token_ref optional field rarely populated | rewire→@api | @api | token ref by @api |

## PERIPHERAL — TG-PERIPH (config, file_handler, log_streamer, notifier, tmux_manager, __init__)

| TAG | TYPE | SOURCE (file:lines) | WHAT | PORT ACTION | DEST | VERIFY |
|---|---|---|---|---|---|---|
| TG-PERIPH-001 | FILE | config.py:1-261 | Legacy+multi-bot config loader | rewire→@api | api/secrets/telegram_config | funcs exist, missing-file tested |
| TG-PERIPH-002 | CONST | config.py:45 | CONFIG_PATH ~/.aipass/telegram_config.json | rewire→@api | get-secret/config | no hardcoded .aipass |
| TG-PERIPH-003 | CONST | config.py:46 | BOT_CONFIG_DIR ~/.aipass/telegram_bots/ | rewire→@api | get-secret/config | no hardcoded path |
| TG-PERIPH-004 | CONST | config.py:48 | REQUIRED_BOT_FIELDS (bot_id,bot_token) | copy-as-is | same file | constant present |
| TG-PERIPH-005 | SECRET | config.py:45,73 | Legacy single-bot token | rewire→@api | get-secret | live token via mgr |
| TG-PERIPH-006 | SECRET | config.py:46,180 | Per-bot tokens | rewire→@api | get-secret | per-bot token via mgr |
| TG-PERIPH-007 | FUNC | config.py:54-81 | load_telegram_config legacy | rewire→@api | api/secrets | returns dict from store |
| TG-PERIPH-008 | FUNC | config.py:84-99 | get_bot_token legacy | rewire→@api | api/secrets | returns token/None |
| TG-PERIPH-009 | FUNC | config.py:102-117 | get_bot_username legacy | rewire→@api | api/secrets | returns username |
| TG-PERIPH-010 | FUNC | config.py:120-135 | get_allowed_user_ids legacy | rewire→@api | api/secrets | returns int list |
| TG-PERIPH-011 | FUNC | config.py:138-152 | validate_config has token | rewire→@api | api/secrets | True only w/ token |
| TG-PERIPH-012 | FUNC | config.py:160-197 | load_bot_config per-bot | rewire→@api | api/secrets | reads store not disk |
| TG-PERIPH-013 | FUNC | config.py:200-223 | list_bot_configs glob stems | rewire→@api | api/secrets | returns bot_ids |
| TG-PERIPH-014 | FUNC | config.py:226-261 | validate_bot_config type-check | copy-as-is | api/secrets | validates token+work_dir |
| TG-PERIPH-015 | WART | config.py:22-27 | Legacy single-bot path parallel to multi-bot | strip | api/secrets | only one path remains |
| TG-PERIPH-016 | FILE | file_handler.py:1-223 | Download+classify+prompt file uploads | copy-as-is | skill/file_handler | text/image/pdf/binary round-trip |
| TG-PERIPH-017 | CONST | file_handler.py:38 | TEMP_DIR /tmp/telegram_uploads | copy-as-is | skill/file_handler | dir created on demand |
| TG-PERIPH-018 | CONST | file_handler.py:39 | MAX_FILE_SIZE 10MB | copy-as-is | skill/file_handler | ValueError on oversize |
| TG-PERIPH-019 | CONST | file_handler.py:40 | TEXT_CONTENT_LIMIT 50000 | copy-as-is | skill/file_handler | long text truncated |
| TG-PERIPH-020 | CONST | file_handler.py:43-49 | SUPPORTED_TEXT_EXTENSIONS | copy-as-is | skill/file_handler | constant present |
| TG-PERIPH-021 | CONST | file_handler.py:52 | IMAGE_EXTENSIONS | copy-as-is | skill/file_handler | constant present |
| TG-PERIPH-022 | CONST | file_handler.py:55-62 | LANGUAGE_MAP | copy-as-is | skill/file_handler | constant present |
| TG-PERIPH-023 | FUNC | file_handler.py:65-77 | _sanitize_filename strip traversal | copy-as-is | skill/file_handler | UUID fallback on empty |
| TG-PERIPH-024 | FUNC | file_handler.py:80-113 | download_telegram_file async to TEMP | copy-as-is | skill/file_handler | live: file in /tmp |
| TG-PERIPH-025 | WART | file_handler.py:111-112 | print() printf-style args (not logged) | strip | skill/file_handler | no bare print, log used |
| TG-PERIPH-026 | WART | file_handler.py:80,111 | dead python-telegram-bot download_to_drive ref | rewire→@api | skill/file_handler | live: upload succeeds e2e |
| TG-PERIPH-027 | FUNC | file_handler.py:116-144 | detect_file_type ext+UTF-8 sniff | copy-as-is | skill/file_handler | each category correct |
| TG-PERIPH-028 | FUNC | file_handler.py:147-212 | build_file_prompt per type | copy-as-is | skill/file_handler | prompt has filename+caption |
| TG-PERIPH-029 | FUNC | file_handler.py:215-223 | cleanup_file unlink silent | copy-as-is | skill/file_handler | temp absent after |
| TG-PERIPH-030 | WART | file_handler.py:222-223 | print() printf-style in cleanup | strip | skill/file_handler | no bare print |
| TG-PERIPH-031 | FILE | log_streamer.py:1-258 | Daemon thread tail logs to Telegram | copy-as-is | skill/log_streamer | lines visible <10s |
| TG-PERIPH-032 | DEP | log_streamer.py:50 | prax get_direct_logger | rewire→@prax | prax logger | no event-pipeline recursion |
| TG-PERIPH-033 | CONST | log_streamer.py:56 | SYSTEM_LOGS_DIR /home/aipass/system_logs hardcoded | rewire→@api | pathlib/config | no /home/aipass literal |
| TG-PERIPH-034 | SEAM | log_streamer.py:56,91 | Hardcoded /home/aipass in glob | rewire→@api | pathlib/config | config-driven, no hardcode |
| TG-PERIPH-035 | CONST | log_streamer.py:57 | BATCH_INTERVAL 5.0s | copy-as-is | skill/log_streamer | sleep cycle verified |
| TG-PERIPH-036 | CONST | log_streamer.py:58 | TELEGRAM_MAX_LENGTH 4000 | copy-as-is | skill/log_streamer | batches <=4000 |
| TG-PERIPH-037 | CLASS | log_streamer.py:66-258 | LogStreamer daemon batched | copy-as-is | skill/log_streamer | start/stop tested, exits clean |
| TG-PERIPH-038 | FUNC | log_streamer.py:89-93 | _get_log_files glob | rewire→@api | pathlib/config | files from config path |
| TG-PERIPH-039 | FUNC | log_streamer.py:95-106 | _init_positions seek EOF | copy-as-is | skill/log_streamer | no dup lines 1st cycle |
| TG-PERIPH-040 | FUNC | log_streamer.py:108-150 | _read_new_lines incremental+rotation | copy-as-is | skill/log_streamer | rotation resets offset 0 |
| TG-PERIPH-041 | FUNC | log_streamer.py:156-172 | _send_message raw urllib POST | copy-as-is | skill/log_streamer | True on 200 |
| TG-PERIPH-042 | FUNC | log_streamer.py:174-199 | _send_batched chunk respecting max | copy-as-is | skill/log_streamer | no msg >4000 |
| TG-PERIPH-043 | FUNC | log_streamer.py:205-222 | _run main daemon loop | copy-as-is | skill/log_streamer | exits on stop event |
| TG-PERIPH-044 | FUNC | log_streamer.py:228-242 | start spawn thread | copy-as-is | skill/log_streamer | alive after, double-start noop |
| TG-PERIPH-045 | FUNC | log_streamer.py:244-258 | stop set event+join timeout | copy-as-is | skill/log_streamer | dead within interval+2s |
| TG-PERIPH-046 | STATE | log_streamer.py:77 | log_positions per-file offsets | copy-as-is | skill/log_streamer | offset advances monotonic |
| TG-PERIPH-047 | FILE | notifier.py:1-117 | Standalone push sender+CLI | rewire→@api | skill/notifier | send returns True live |
| TG-PERIPH-048 | CONST | notifier.py:45 | CONFIG_PATH ~/.aipass/scheduler_config.json | rewire→@api | get-secret | no hardcoded path |
| TG-PERIPH-049 | SECRET | notifier.py:45,69-71 | Scheduler bot token+chat_id | rewire→@api | get-secret | token via mgr not disk |
| TG-PERIPH-050 | SEAM | notifier.py:45,69 | Separate scheduler token distinct from bridge | rewire→@api | get-secret | single store lookup |
| TG-PERIPH-051 | WART | notifier.py:20-28,45 | Duplicate-notification: scheduler bot vs per-bot | strip | skill/notifier | single path, dedup confirmed |
| TG-PERIPH-052 | FUNC | notifier.py:52-91 | send_telegram_notification urllib+opts | rewire→@api | skill/notifier | live: notification received |
| TG-PERIPH-053 | FUNC | notifier.py:98-117 | CLI __main__ --silent/--markdown | rewire→@cli | skill/notifier | python3 notifier.py exits 0 |
| TG-PERIPH-054 | FILE | tmux_manager.py:1-317 | tmux helpers+bot_id+AIPASS_SESSION_TYPE | keep(tmux/systemd) | skill/tmux_manager | sessions created/killed |
| TG-PERIPH-055 | CONST | tmux_manager.py:47 | SESSION_PREFIX "telegram-" | keep(tmux/systemd) | skill/tmux_manager | names start telegram- |
| TG-PERIPH-056 | CONST | tmux_manager.py:48 | DEFAULT_BRANCH "dev_central" | copy-as-is | skill/tmux_manager | used as fallback |
| TG-PERIPH-057 | CONST | tmux_manager.py:49 | CLAUDE_BIN ~/.local/bin/claude hardcoded | keep(tmux/systemd) | skill/tmux_manager | claude launches |
| TG-PERIPH-058 | SEAM | tmux_manager.py:49 | CLAUDE_BIN hardcoded breaks other installs | keep(tmux/systemd) | skill/tmux_manager | path resolves, no FileNotFound |
| TG-PERIPH-059 | CONST | tmux_manager.py:50 | SEND_KEYS_DELAY 0.5s | keep(tmux/systemd) | skill/tmux_manager | constant present |
| TG-PERIPH-060 | CONST | tmux_manager.py:53 | RENAME_DELAY 3s | keep(tmux/systemd) | skill/tmux_manager | /rename after delay |
| TG-PERIPH-061 | FUNC | tmux_manager.py:56-58 | _session_name prefix+branch | keep(tmux/systemd) | skill/tmux_manager | returns telegram-{branch} |
| TG-PERIPH-062 | FUNC | tmux_manager.py:61-68 | _send_rename sleep+/rename send-keys | keep(tmux/systemd) | skill/tmux_manager | renamed in /resume picker |
| TG-PERIPH-063 | WART | tmux_manager.py:63 | time.sleep(RENAME_DELAY) blocks caller thread | keep(tmux/systemd) | skill/tmux_manager | no caller stall; async noted |
| TG-PERIPH-064 | FUNC | tmux_manager.py:71-73 | has_tmux shutil.which | keep(tmux/systemd) | skill/tmux_manager | False when tmux absent |
| TG-PERIPH-065 | FUNC | tmux_manager.py:76-92 | session_exists has-session | keep(tmux/systemd) | skill/tmux_manager | True for live |
| TG-PERIPH-066 | FUNC | tmux_manager.py:94-167 | create_session new+Claude+rename | keep(tmux/systemd) | skill/tmux_manager | session in tmux ls, claude running |
| TG-PERIPH-067 | WART | tmux_manager.py:114-135 | create_session print() printf-style (not logged) | strip | skill/tmux_manager | proper logger used |
| TG-PERIPH-068 | WART | tmux_manager.py:94-167 | create_session UNUSED — base_bot inline path is real | strip | skill/tmux_manager | single session-create path |
| TG-PERIPH-069 | SEAM | tmux_manager.py:139-144 | AIPASS_BOT_ID via tmux set-environment | keep(tmux/systemd) | skill/tmux_manager | $AIPASS_BOT_ID set in pane |
| TG-PERIPH-070 | SEAM | tmux_manager.py:149-151 | AIPASS_SESSION_TYPE=telegram in claude_cmd | keep(tmux/systemd) | skill/tmux_manager | $AIPASS_SESSION_TYPE=telegram |
| TG-PERIPH-071 | FUNC | tmux_manager.py:170-221 | send_message async literal send-keys+Enter | keep(tmux/systemd) | skill/tmux_manager | msg in pane, Claude responds |
| TG-PERIPH-072 | WART | tmux_manager.py:170-221 | send_message print-style logs | strip | skill/tmux_manager | no bare print |
| TG-PERIPH-073 | FUNC | tmux_manager.py:224-256 | kill_session idempotent | keep(tmux/systemd) | skill/tmux_manager | absent after call |
| TG-PERIPH-074 | FUNC | tmux_manager.py:259-287 | list_sessions parse telegram-* | keep(tmux/systemd) | skill/tmux_manager | returns active branch names |
| TG-PERIPH-075 | FUNC | tmux_manager.py:290-317 | get_session_pane capture-pane | keep(tmux/systemd) | skill/tmux_manager | returns pane string |
| TG-PERIPH-076 | FILE | __init__.py:1-32 | Package init re-export legacy config funcs | rewire→@api | skill/__init__ | __all__ matches public surface |
| TG-PERIPH-077 | WART | __init__.py:22-26 | Exports only legacy funcs, multi-bot not exported | rewire→@api | skill/__init__ | __all__ includes multi-bot funcs |
| TG-PERIPH-078 | DEP | file_handler.py:29-35 | sys.path.insert AIPASS_ROOT hack | strip | skill/file_handler | no sys.path manip |
| TG-PERIPH-079 | DEP | log_streamer.py:37-41 | sys.path.insert AIPASS_ROOT hack | strip | skill/log_streamer | no sys.path manip |
| TG-PERIPH-080 | DEP | config.py:31-35 | sys.path.insert AIPASS_ROOT hack | strip | api/secrets | no sys.path manip |
| TG-PERIPH-081 | DEP | notifier.py:31-35 | sys.path.insert AIPASS_ROOT hack | strip | skill/notifier | no sys.path manip |
| TG-PERIPH-082 | DEP | tmux_manager.py:37-41 | sys.path.insert AIPASS_ROOT hack | strip | skill/tmux_manager | no sys.path manip |
| TG-PERIPH-083 | SEAM | notifier.py:45 | Parallel hardcode pattern mirrors log_streamer | strip | skill/notifier | no /home/aipass refs |
| TG-PERIPH-084 | CONFIG | config.py:45 | ~/.aipass/telegram_config.json legacy | rewire→@api | get-secret | not read from disk |
| TG-PERIPH-085 | CONFIG | config.py:46 | ~/.aipass/telegram_bots/ per-bot dir | rewire→@api | get-secret | not scanned at runtime |
| TG-PERIPH-086 | CONFIG | notifier.py:45 | ~/.aipass/scheduler_config.json | rewire→@api | get-secret | not read from disk |

## TESTS + INFRA — TG-TEST / TG-INFRA

| TAG | TYPE | SOURCE | WHAT | PORT ACTION | DEST | VERIFY |
|---|---|---|---|---|---|---|
| TG-TEST-001 | TEST | tests/test_response_router.py (830L, 53 fns) | router match/expiry/CWD-tree/fallback | copy-as-is | skill tests/, rewire imports | ported + green |
| TG-TEST-002 | TEST | tests/test_multibot_integration.py (522L, 26 fns) | tmux, pending v2, sidechain-skip, chunk | copy-as-is | skill tests/, rewire imports | ported + green; sidechain passes |
| TG-TEST-003 | TEST | tests/test_log_streamer.py (616L, 41 fns) | position track, send-batched, start/stop | copy-as-is | skill tests/, rewire imports | ported + green |
| TG-TEST-004 | TEST | tests/test_multi_bot.py (1838L, 145 fns) | BaseBot+BranchPlugin; lock-PID-reuse + shared-session | copy-as-is | skill tests/, rewire imports | ported + green; both classes pass |
| TG-TEST-005 | TEST | tests/test_bot_registry.py (654L, 48 fns) | Registry CRUD | copy-as-is | skill tests/, rewire imports | ported + green |
| TG-TEST-006 | TEST | tests/test_botfather_client.py (863L, 49 fns) | BotFather Telethon client | copy-as-is | skill tests/, rewire imports | ported + green |
| TG-TEST-007 | TEST | tests/test_multibot_config.py (842L, 67 fns) | config/parse-command/text builders/ops | copy-as-is | skill tests/, rewire imports | ported + green |
| TG-TEST-008 | FUNC | tests/conftest.py:26-60 _redirect_prax_logs | session autouse: redirect prax logger to tmp | copy-as-is | skill tests/conftest.py | pytest exits 0; no real-log entries |
| TG-TEST-009 | WART | tests/conftest.py:26-60 | Without fixture tests pollute real logs→false Trigger alerts | copy-as-is | conftest before test imports | Trigger zero test-run events |
| TG-TEST-010 | SEAM | test_multi_bot.py:1773-1838 TestLockPidReuse (5 fns) | live PID running different bot-id clears stale lock | copy-as-is | with TG-TEST-004 | all 5 green |
| TG-TEST-011 | SEAM | test_multi_bot.py:1637-1765 TestSharedSession (8 fns) | shared_session=pc attach/protect/pending name | copy-as-is | with TG-TEST-004 | all 8 green |
| TG-TEST-012 | SEAM | test_multibot_integration.py:413-434 | isSidechain entries skipped by extractor | copy-as-is | with TG-TEST-002 | test green |
| TG-INFRA-001 | INFRA | ~/.config/systemd/user/telegram-bot@.service (not on disk) | systemd template, one instance/bot, %i, restart 10s; ExecStart=branch_plugin.py --bot-id %i | keep(tmux/systemd) | AIPass service unit | systemctl status active; getMe ok |
| TG-INFRA-002 | CONFIG | .claude/settings.json:116-133 Stop block | Stop event telegram_response.py, timeout:30 | rewire→@hooks | AIPass hook engine | hook registered, fires <30s |
| TG-INFRA-003 | DEP | settings.json env + DEV_CENTRAL.local.json:89 | AIPASS_BOT_ID injected by BaseBot; CWD fallback shared | register | tmux env or CWD infer | echo $AIPASS_BOT_ID correct |
| TG-INFRA-004 | DEP | .claude.json:200 hasTrustDialogAccepted:true | trust dialog accepted for each bot work_dir | register | AIPass .claude.json per work_dir | bots start, no trust block |
| TG-INFRA-005 | INFRA | bot_factory.py:64 SYSTEMD_DIR | systemd dir from home; systemctl --user | rewire→@api | path if home differs | enable_service True |
| TG-INFRA-006 | INFRA | .aipass/telegram_bots/telethon_auth.py | one-time Telethon phone auth, creates session | keep(tmux/systemd) | copy to skill, run once | check_telethon_setup ready |
| TG-INFRA-007 | SECRET | .aipass/telegram_bots/base.json | base bot token+allowed_user_ids | rewire→@api | ~/.secrets/aipass/telegram/base.json | jq .bot_token non-empty |
| TG-INFRA-008 | SECRET | .aipass/telegram_bots/dev_central.json | dev_central token+allowed+shared_session | rewire→@api | ~/.secrets/aipass/telegram/dev_central.json | bot starts cleanly |
| TG-INFRA-009 | SECRET | .aipass/telegram_bots/flow.json | flow token+allowed | rewire→@api | ~/.secrets/aipass/telegram/flow.json | bot starts cleanly |
| TG-INFRA-010 | SECRET | .aipass/telegram_bots/patrick_private.json | patrick_private token+allowed+username | rewire→@api | ~/.secrets/aipass/telegram/patrick_private.json | bot starts cleanly |
| TG-INFRA-011 | SECRET | .aipass/telegram_bots/seed.json | seed token+allowed | rewire→@api | ~/.secrets/aipass/telegram/seed.json | bot starts cleanly |
| TG-INFRA-012 | SECRET | .aipass/telegram_bots/test.json | test token+allowed | rewire→@api | ~/.secrets/aipass/telegram/test.json | bot starts cleanly |
| TG-INFRA-013 | SECRET | .aipass/telegram_bots/vera.json | vera token+allowed | rewire→@api | ~/.secrets/aipass/telegram/vera.json | bot starts cleanly |
| TG-INFRA-014 | SECRET | .aipass/telegram_bots/.telethon_config.json | api_id+api_hash MTProto creds | rewire→@api | ~/.secrets/aipass/telegram/.telethon_config.json | jq .api_id non-empty |
| TG-INFRA-015 | SECRET | .aipass/telegram_bots/.telethon.session | Telethon session binary (no expiry) | rewire→@api | ~/.secrets/aipass/telegram/.telethon.session | check_telethon_setup ready |
| TG-INFRA-016 | STATE | .aipass/telegram_bots/_registry.json | central registry all bots | copy-as-is | stays w/ skill | jq .bots lists 7 ids |
| TG-INFRA-017 | STATE | .aipass/telegram_bots/base_offset.json | update offset base | copy-as-is | stays w/ skill | jq .offset int |
| TG-INFRA-018 | STATE | .aipass/telegram_bots/dev_central_offset.json | update offset dev_central | copy-as-is | stays w/ skill | jq .offset int |
| TG-INFRA-019 | STATE | .aipass/telegram_bots/patrick_private_offset.json | update offset patrick_private | copy-as-is | stays w/ skill | jq .offset int |
| TG-INFRA-020 | STATE | .aipass/telegram_bots/test_offset.json | update offset test | copy-as-is | stays w/ skill | jq .offset int |
| TG-INFRA-021 | STATE | .aipass/telegram_bots/vera_offset.json | update offset vera | copy-as-is | stays w/ skill | jq .offset int |
| TG-INFRA-022 | STATE | .aipass/telegram_bots/.base.lock | PID lock base | copy-as-is | stays w/ skill, clear on deploy | _check_lock False after deploy |
| TG-INFRA-023 | STATE | .aipass/telegram_bots/.dev_central.lock | PID lock dev_central | copy-as-is | stays w/ skill | lock absent or correct PID |
| TG-INFRA-024 | STATE | .aipass/telegram_bots/.flow.lock | PID lock flow | copy-as-is | stays w/ skill | lock absent or correct PID |
| TG-INFRA-025 | STATE | .aipass/telegram_bots/.patrick_private.lock | PID lock patrick_private | copy-as-is | stays w/ skill | lock absent or correct PID |
| TG-INFRA-026 | STATE | .aipass/telegram_bots/.seed.lock | PID lock seed | copy-as-is | stays w/ skill | lock absent or correct PID |
| TG-INFRA-027 | STATE | .aipass/telegram_bots/.vera.lock | PID lock vera | copy-as-is | stays w/ skill | lock absent or correct PID |
| TG-INFRA-028 | WART | telegram_response.py:484-495 | SubagentStop + /subagents/ filters; missing=dup messages | copy-as-is | telegram_response.py verbatim | no dup on Task agent complete |
| TG-INFRA-029 | WART | DEV_CENTRAL.local.json:89 CWD bot_id fallback | shared sessions no AIPASS_BOT_ID; scan *.json by work_dir | rewire→@api | _infer_bot_id_from_cwd ported | logger IDs bot in shared session |
| TG-INFRA-030 | INFRA | tests/.archive/test_telegram_bridge.py | archived legacy bridge test | strip | discard | not in AIPass tests/ |

---
*Generated S233 (2026-06-15) by 5 read-only mapping agents over Dev-Pass telegram source. Source of truth for the port's completeness audit.*
