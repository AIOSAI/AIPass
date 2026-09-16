# Known issues

Standing defects and single-machine measurements, each with the reading behind it.

Moved out of `README.md` on 2026-09-15 (DPLAN-0347, the layer contract): the README is the
face, the depth lives here. Back to the [branch README](../README.md).

---

## Known Issues
- **inotify pressure** — The monitor and log watcher fall back to polling when inotify watches run out (functional but slower). Earlier revisions said the system is "often near" the limit; measured again 2026-09-05 it is not — **8,340 watches held across all processes against a `max_user_watches` of 65,536**, about 13% (it was 7,664 on 2026-08-25). The fallback is real and tested. It is a single-machine reading, not a fleet property.
- **`monitor run` is not single-instance.** `instance_lock` guards the *Telegram relay* only, so N concurrent Mission Controls start cleanly and each adds its own watches on top of every other watcher (see the inotify note above). Verified 2026-08-13 by launching five alongside the then-live systemd service; none complained. That service is retired as of 2026-08-18 (monitor is on-request only), so the everyday risk is now several forgotten terminals rather than a daemon plus terminals — but the missing guard is unchanged.
- ~~**Error paths exit 0.**~~ **Fixed 2026-09-07** (FPLAN-0492 wave 3). Every unknown token now exits **1** with the token named on stderr: measured after the change, `--definitely-not-a-flag`, `monitor bogus`, `log-audit bogus`, `log-health bogus`, `dashboard bogus` and `status bogus` all return 1, and `status`, `log-health scan`, `dashboard status`, `log-audit audit`, `monitor --help` and `dashboard template-status` still return 0. See the unknown-argument gate in [architecture.md](architecture.md).
- **The test seam does not cover path-based writes.** `AIPASS_TEST_LOG_DIR` redirects everything the json service writes by module name (measured 2026-09-05: 0 files into the real `prax_json/`, 18 into the redirect). It does not reach the module-level constants in `handlers/config/load.py`, `handlers/config/ignore_patterns.py`, `handlers/registry/load.py` and `handlers/registry/save.py`, which resolve to the real tree even with the variable set — so a registry save under any suite writes the live `prax_registry.json`. See [json_service.md](json_service.md).
- **The module registry never prunes.** `prax_registry.json` gains an entry when a `.py` file appears and loses one only if someone removes it by hand. Counted 2026-09-05: **196 modules registered, 63 of which name a file that is no longer on disk** — probes, scratch files and archived tests from a dozen branches' sweeps. Stale rows mislead rather than break (every reader opens the path), but a third of the registry describing files that do not exist is not a registry anyone should trust for a count.
- **No runtime filtering in Mission Control** — `_handle_interactive_cmd` dispatches
  only `help` and `status`; `watch` and `filter` fall through to "Unknown command". Branch
  selection is launch-time only (`monitor run seedgo,cli`) and cannot be changed without a
  restart. Commons feed mode is the exception: it implements `filter <room>` / `filter clear`
  live. `watch` exists in neither mode.
