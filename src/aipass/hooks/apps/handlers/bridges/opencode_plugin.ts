// AIPass hooks for OpenCode 2, installed as ~/.config/opencode/plugins/aipass.ts (a byte-equal copy).
// Runs the manifest's cli.opencode rows through bridges/opencode.py; all mapping and judging is Python's.
import { Plugin } from "@opencode/plugin"
import { appendFileSync, readFileSync } from "node:fs"
import { join } from "node:path"

type Row = { event: string; command: string; timeout?: number }
type Entry = { key: string; value: string }
type Answer = { deny?: string; context?: string; entry?: Entry; entries?: Entry[] }

const BROKEN = (error: string) =>
  `HOOKS BROKEN: the AIPass hook engine could not run (${error}).\n` +
  "Every gate it runs is down, so nothing they guard runs until it is fixed.\n" +
  'Mail @hooks and @devpulse: drone @ai_mail email @hooks "Hooks broken" "<what you ran, and this text>"'

export default Plugin.define({
  id: "aipass",
  async setup(ctx: any) {
    const home = process.env.AIPASS_HOME ?? ""
    // The service's process.cwd() is wherever it was started; the seat is the location's directory.
    const cwd: string = ctx.location.directory
    const logError = (message: string) => {
      const line = `${new Date().toISOString()} | bridges.opencode_plugin | ERROR | ${message.split("\n")[0]}\n`
      try {
        appendFileSync(join(home, "src", "aipass", "hooks", "logs", "bridge.log"), line)
      } catch {
        console.error(line)
      }
    }

    let rows: Row[] = []
    let unwired = ""
    try {
      if (!home) throw new Error("AIPASS_HOME is not set in the OpenCode server's environment")
      const manifest = JSON.parse(readFileSync(join(home, ".claude", "provider_manifest.json"), "utf8"))
      rows = manifest?.cli?.opencode?.hooks ?? []
      if (!rows.length) throw new Error("the provider manifest has no cli.opencode rows")
    } catch (e) {
      unwired = `AIPass hooks are unwired in this OpenCode server: ${e}. Mail @hooks.`
      logError(unwired)
    }

    const call = (row: Row, payload: object): Answer & { broken?: string } => {
      const argv = row.command.split(/\s+/).filter(Boolean).map((w) => w.replaceAll("$AIPASS_HOME", home))
      try {
        const r = Bun.spawnSync(argv, {
          cwd,
          stdin: Buffer.from(JSON.stringify(payload)),
          timeout: (row.timeout ?? 60) * 1000,
        })
        if (r.exitCode !== 0) return { broken: `${argv.at(-1)} exited ${r.exitCode}: ${r.stderr.toString().trim()}` }
        return JSON.parse(r.stdout.toString())
      } catch (e) {
        return { broken: `${argv.at(-1)}: ${e}` }
      }
    }

    // Every row of the event in manifest order; the first deny answers, contexts join in order, entries collect.
    const run = (event: string, payload: object): Answer => {
      const contexts: string[] = []
      const entries: Entry[] = []
      for (const row of rows.filter((r) => r.event === event)) {
        const answer = call(row, { ...payload, hook_event_name: event })
        if (answer.broken) {
          logError(answer.broken)
          if (event === "PreToolUse") return { deny: BROKEN(answer.broken) }
          continue
        }
        if (answer.deny) return { deny: answer.deny }
        if (answer.entry) entries.push(answer.entry)
        if (answer.context) contexts.push(answer.context)
      }
      return { ...(contexts.length ? { context: contexts.join("\n\n") } : {}), ...(entries.length ? { entries } : {}) }
    }

    const base = (sessionID: string) => ({ session_id: sessionID, cwd, provider: "opencode" })
    const started = new Set<string>()

    await ctx.session.hook("prompt", async (event: any) => {
      const parts: string[] = []
      if (unwired) parts.push(unwired)
      else {
        if (!started.has(event.sessionID)) {
          started.add(event.sessionID)
          parts.push(run("SessionStart", { ...base(event.sessionID), source: "startup" }).context ?? "")
        }
        const answer = run("UserPromptSubmit", {
          ...base(event.sessionID),
          prompt: event.prompt?.text ?? "",
          keeps_entries: true,
        })
        // OpenCode cannot withhold a prompt from a plugin: a refusal travels with it instead.
        parts.push(answer.deny ?? answer.context ?? "")
        // Keyed entries sit in the instruction block of every model call and survive a compaction; one that
        // cannot be kept travels with the prompt, so the text arrives once either way.
        for (const entry of answer.deny ? [] : answer.entries ?? []) {
          try {
            await ctx.session.instructions.entry.put({ sessionID: event.sessionID, key: entry.key, value: entry.value })
          } catch (e) {
            logError(`instruction entry ${entry.key} not kept, sent with the prompt: ${e}`)
            parts.push(entry.value)
          }
        }
      }
      const added = parts.filter(Boolean).join("\n\n")
      if (added && event.prompt) event.prompt.text = `${event.prompt.text}\n\n${added}`
    })

    await ctx.tool.hook("execute.before", async (event: any) => {
      if (unwired) throw new Error(BROKEN(unwired))
      const answer = run("PreToolUse", { ...base(event.sessionID), tool: event.tool, input: event.input })
      if (answer.deny) throw new Error(answer.deny)
    })

    await ctx.tool.hook("execute.after", async (event: any) => {
      if (unwired) return
      const response = event.status === "error" ? { error: event.error } : event.result
      run("PostToolUse", { ...base(event.sessionID), tool: event.tool, input: event.input, tool_response: response })
    })

    try {
      await ctx.session.hook("compaction", async (event: any) => {
        // OpenCode 2.2's compaction event names no reason: auto, overflow and manual all read as auto.
        if (!unwired) run("PreCompact", { ...base(event.sessionID), trigger: event.reason ?? "auto" })
      })
    } catch (e) {
      logError(`compaction hook unavailable, PreCompact rows do not fire: ${e}`)
    }

    const controller = new AbortController()
    void (async () => {
      try {
        for await (const ev of ctx.event.subscribe({ signal: controller.signal })) {
          const type = (ev as any).type
          const sessionID = (ev as any).data?.sessionID
          if (!unwired && sessionID && (type === "session.execution.succeeded" || type === "session.execution.failed")) {
            run("Stop", { ...base(sessionID), stop_hook_active: false })
          }
        }
      } catch (e) {
        if (!controller.signal.aborted) logError(`event stream ended, Stop rows do not fire: ${e}`)
      }
    })()
    return () => controller.abort()
  },
})
