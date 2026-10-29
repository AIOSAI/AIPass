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

    // Async: a synchronous spawn holds the server's one JavaScript thread for the whole row. Stop is the
    // exception: a standalone run exits on idle, before an awaited spawn finishes, and the turn is over anyway.
    const call = async (row: Row, payload: object, sync: boolean): Promise<Answer & { broken?: string }> => {
      const argv = row.command.split(/\s+/).filter(Boolean).map((w) => w.replaceAll("$AIPASS_HOME", home))
      const stdin = Buffer.from(JSON.stringify(payload))
      const timeout = (row.timeout ?? 60) * 1000
      try {
        if (sync) {
          const r = Bun.spawnSync(argv, { cwd, stdin, timeout })
          if (r.exitCode !== 0) return { broken: `${argv.at(-1)} exited ${r.exitCode}: ${r.stderr.toString().trim()}` }
          return JSON.parse(r.stdout.toString())
        }
        const proc = Bun.spawn(argv, {
          cwd,
          stdin,
          stdout: "pipe",
          stderr: "pipe",
          timeout,
        })
        const [stdout, stderr, exitCode] = await Promise.all([
          new Response(proc.stdout).text(),
          new Response(proc.stderr).text(),
          proc.exited,
        ])
        if (exitCode !== 0) return { broken: `${argv.at(-1)} exited ${exitCode}: ${stderr.trim()}` }
        return JSON.parse(stdout)
      } catch (e) {
        return { broken: `${argv.at(-1)}: ${e}` }
      }
    }

    // Every row of the event in manifest order; the first deny answers, contexts join in order, entries collect.
    const run = async (event: string, payload: object): Promise<Answer> => {
      const contexts: string[] = []
      const entries: Entry[] = []
      for (const row of rows.filter((r) => r.event === event)) {
        const answer = await call(row, { ...payload, hook_event_name: event }, event === "Stop")
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
        const entries: Entry[] = []
        if (!started.has(event.sessionID)) {
          started.add(event.sessionID)
          const start = await run("SessionStart", { ...base(event.sessionID), source: "startup", keeps_entries: true })
          parts.push(start.context ?? "")
          entries.push(...(start.entries ?? []))
        }
        const answer = await run("UserPromptSubmit", {
          ...base(event.sessionID),
          prompt: event.prompt?.text ?? "",
          keeps_entries: true,
        })
        // OpenCode cannot withhold a prompt from a plugin: a refusal travels with it instead.
        parts.push(answer.deny ?? answer.context ?? "")
        if (!answer.deny) entries.push(...(answer.entries ?? []))
        // Keyed entries sit in the instruction block of every model call and survive a compaction; one that
        // cannot be kept travels with the prompt, so the text arrives once either way.
        for (const entry of entries) {
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
      const call = { ...base(event.sessionID), tool: event.tool, input: event.input, tool_use_id: event.id }
      const answer = await run("PreToolUse", call)
      if (answer.deny) throw new Error(answer.deny)
    })

    await ctx.tool.hook("execute.after", async (event: any) => {
      if (unwired) return
      const response = event.status === "error" ? { error: event.error } : event.result
      const answer = await run("PostToolUse", {
        ...base(event.sessionID),
        tool: event.tool,
        input: event.input,
        tool_use_id: event.id,
        tool_response: response,
      })
      // OpenCode reads result.content after this hook returns: a report pushed there reaches the model.
      if (answer.context && Array.isArray(event.result?.content)) {
        event.result.content.push({ type: "text", text: answer.context })
      }
    })

    try {
      await ctx.session.hook("compaction", async (event: any) => {
        // OpenCode 2.2's compaction event names no reason: auto, overflow and manual all read as auto.
        if (!unwired) await run("PreCompact", { ...base(event.sessionID), trigger: event.reason ?? "auto" })
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
            await run("Stop", { ...base(sessionID), stop_hook_active: false })
          }
        }
      } catch (e) {
        if (!controller.signal.aborted) logError(`event stream ended, Stop rows do not fire: ${e}`)
      }
    })()
    return () => controller.abort()
  },
})
