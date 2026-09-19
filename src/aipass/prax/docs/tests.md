[<- Back to the README](../README.md)

# Tests — the suite and its conventions

How the suite is organised, what the fixtures guarantee, and how to run it.

---

## Running the suite

`pytest tests/` from the branch root runs everything; `drone @seedgo audit aipass @prax`
scores the sources behind it. The case count is whatever the run reports — it is not written
down here, because it changes on the commit that adds a test.

New test files are gated by policy: extend an existing file, or mail @devpulse with the
defect or contract a new file would pin.

## What each file covers

One row per file, no counts: the count belongs to the run, the coverage belongs here.

| Test File | Coverage |
|---|---|
| test_filesystem_handler.py | Multi-CLI adapters, Codex branch detection |
| test_monitoring_handlers.py | Branch detector, stream output, event handling, the registry read that opens instead of checking |
| test_operations.py | Dashboard operations, write-through; `refresh @branch` through the caller's project registry (core wins a collision), the caller's directory over the process cwd, mail counted from the branch's own inbox |
| test_json_handler.py | The fleet json service: branch resolution, the per-call seam, document modes, the NaN refusal, the exception table, bounded retry, the log cap, the data-leg bump and heal (incl. rate_tracker sharing the document), the shim binds-never-wraps |
| test_log_watcher.py | Log file tailing, agent activity parsing |
| test_monitor_module.py | Monitor commands, thread lifecycle (4-thread), branch scoping |
| test_telegram_relay.py | Telegram relay, buffering, pause control |
| test_config.py | Config loading, path resolution, log levels |
| test_repo_root.py | Repo-root resolution with a dead working directory, per-platform expectation tables |
| test_logger_module.py | Logger init, routing, lifecycle, NullLogger fallback, lazy-init import footprint (subprocess) |
| test_event_queue.py | Thread-safe event buffering, scope suppression |
| test_logging_handlers.py | Setup, rotation, introspection, direct logger |
| test_logging.py | Core logging system, debug level gating |
| test_watcher.py | File watcher behaviour; dispatcher survives handler failure (real observer); liveness reporting; the background start that does not block its caller |
| test_monitoring_filters.py | Event filtering rules |
| test_branch_scope.py | Branch scope parsing, label matching, attribution |
| test_dashboard_merge.py | quick_status merge, foreign-key preservation, plan-count shapes, push-template writer, action_required/summary agreement |
| test_help_flag_safety.py | Help flags in any position never execute; ownership before help; free-text safety; the unknown-argument gate (top-level flag, sub-argument, exit code, did-you-mean) |
| test_rate_tracker.py | Rate tracking, thresholds, persistence (incl. rate history), suppression |
| test_instance_lock.py | Single-instance locking, stale reclaim |
| test_commons_feed.py | Commons live feed, cursors, room filtering, full-body rendering |
| test_discovery.py | Module scanning |
| test_display_resilience.py | Markup escaping, display-worker survival, standalone args |
| test_flow_section_contract.py | `sections.flow` five-key contract; per-branch recently_closed; total_plans carried, not derived |
| test_registry.py | Module registry |
| test_project_citizens.py | projects/* registry sweep, passport resolution, collision precedence, CWD-independent paths |
| test_central.py | Central reader |
| test_log_audit.py | Log audit |
| test_help_markup.py | Rendered console output (real Rich console), help covers every routable command |
| test_pid_cache.py | PID resolution cache |
| test_devpulse_dashboard_plugin.py | Dashboard plugin (git, session, dispatch) |
| test_jsonl_writer.py | JSONL append writer |
| test_status.py | Status commands; an unknown sub-argument is refused rather than ignored |
| test_log_health.py | Snapshot staleness reporting, rate display, routing |
| test_sweep.py | Log sweep |
| test_json_durability.py | `AIPASS_TEST_LOG_DIR` seam, measured in subprocesses (both import orderings) |

