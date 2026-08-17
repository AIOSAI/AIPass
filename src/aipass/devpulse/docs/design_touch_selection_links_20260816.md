# Phone terminal: touch selection + links — research synthesis (2026-08-16)

Two-agent web research (prior art + xterm.js source dive), distilled for the @baud build brief.
Status: awaiting Patrick's go. Keyboard-gating round (bottom-5-rows, phone-D2U0hrLz.js) already accepted.

## The landscape (prior-art agent)

- NO browser-based terminal has shipped touch selection working alongside tmux/vim mouse
  reporting: VS Code web terminal (ms' own — issue #261958 open), code-server, ttyd, wetty —
  all known-broken or unaddressed. The gap is industry-wide, not our misunderstanding.
- Native apps solved it with an EXPLICITLY ENTERED local selection mode decoupled from mouse
  forwarding: Blink Shell (long-press enters client-owned drag mode), Termius (OS handles).
  Desktop precedent for the same conflict: Shift-click bypasses tmux in iTerm2/Windows Terminal.
  Touch has no Shift -> a mode toggle is the honest equivalent.
- xterm.js upstream: issues #5377 / #3727 open; PR #5961 (native selection on DOM rows,
  preserves mouse reporting) stalled unmerged, iOS-first. Blueprint, not a dependency.

## The mechanism (techniques agent — code-verified at master)

### Route 1 (RECOMMENDED): modal select-mode via shift-forced synthetic MouseEvents
- xterm has a BUILT-IN "force local selection, bypass app mouse reporting" path keyed on
  shiftKey: SelectionService.shouldForceSelection() (SelectionService.ts:437-446) returns
  event.shiftKey on non-Mac. MouseService._handleMouseDown independently checks the same and
  SKIPS pty forwarding when true. Both are intentional features, not internals.
- Select-mode ON:
  1. preventDefault() on touchstart — kills browser touch->mouse synthesis, so the normal
     tap-forward pipeline never fires for the gesture.
  2. Dispatch synthetic mousedown {clientX, clientY, shiftKey:true, button:0, bubbles:true}
     AT THE TERMINAL ELEMENT — SelectionService + MouseService both see it; selection is
     forced, nothing goes to tmux. event.detail drives single/double/triple = word/line modes
     for free.
  3. Dispatch synthetic mousemove/mouseup {shiftKey:true, buttons:1} AT DOCUMENT, not the
     element — SelectionService's per-gesture document listeners receive them; MouseService's
     persistent element-bound drag listener (which does NOT re-check shouldForceSelection per
     move) never sees them -> no drag reports leak to tmux mid-gesture.
- App owns: the select chip, suppressing normal tap-forward while active, drawing start/end
  drag handles (xterm draws highlight, no handle UI), copy button driven by
  getSelection()/hasSelection()/onSelectionChange (all public API).
- Public API confirmed: select(col,row,len), selectLines, selectAll, getSelection,
  getSelectionPosition, hasSelection, clearSelection, onSelectionChange. NOTE: select()
  REPLACES (clears first) — no public extend; if handles recompute ranges, track own anchor
  and recompute full range per move.
- Pixel->cell hit-testing NOT public (_core._mouseCoordsService only). DOM sidestep:
  document.caretPositionFromPoint (Baseline Dec 2025; verify on device) — but Route 1 mostly
  avoids needing it since xterm does its own coords from the synthetic events.
- RISKIEST UNKNOWN (smoke-test FIRST on the S24 before building the full round): does Firefox
  Android derive pageX/pageY/.buttons/.detail from a CONSTRUCTED MouseEvent such that xterm's
  coordinate math works? One throwaway test: dispatch synthetic shift-mousedown/mousemove/
  mouseup and check getSelection() returns expected text.

### Route 2 (fallback): screenReaderMode accessibility tree
- Native selection on live rows is DEAD: DomRenderer wipes row contents via replaceChildren()
  on every repaint — any native Range dies. Confirmed at source.
- BUT xterm ships a stable, natively selectable parallel text layer: .xterm-accessibility-tree
  (screenReaderMode:true). PR #4742 (merged, 5.4.0) made it user-select:text + syncs
  selectionchange -> term.select(). Flipping screenReaderMode during select-mode could hand us
  Android's real handles + floating copy menu on stable text.
- Unknowns: aria-live chatter, double-render cleanliness, per-gesture flip cost. Nobody has
  shipped this as a mobile-copy hack. Use only if Route 1's synthetic-event unknown fails.

### Links: build the list chip, do NOT load WebLinksAddon as-is
- WebLinksAddon default handleLink opens on PLAIN tap (no modifier check — docs' ctrl/cmd
  language applies only to custom OSC-8 handlers). Its Linkifier listeners are independent of
  MouseService — CONFIRMED architecture: a tap on a URL would BOTH open the link AND send the
  click to tmux. Collision by design, not a maybe.
- Sidestep (no prior art, but trivially sound): links chip scans terminal.buffer.active
  visible lines with WebLinksAddon's own strictUrlRegex -> renders app-level tappable list ->
  window.open. Zero gesture conflict. OSC 8 hyperlinks supported in xterm if we ever want
  richer sources.

### Copy (plain-http context)
- navigator.clipboard unavailable (insecure context). document.execCommand('copy') inside a
  SYNCHRONOUS user-gesture handler is the lane; the Firefox-Android-fails claim traced to a
  Fennec-era <menuitem> bug (Bugzilla 1420466) — not evidence against a normal handler. Cheap
  device verify. NO async gap (promise/setTimeout) between gesture and execCommand or user
  activation is lost.

### Firefox Android gotchas (for the builder)
- preventDefault() on touchend does NOT cancel the synthetic click (Bugzilla 1016480, differs
  from Chrome) — guard the click handler itself while select-mode is active.
- Synthetic click fires at the ORIGINAL touch target even if finger moved before lift
  (Bugzilla 1066157) — matters if gating by movement distance.
- Long-press over user-select:none: suppression via contextmenu preventDefault is the
  documented lane (Bugzilla 1481923); passive CSS-only behavior undocumented — device-test.
- inputMode=none/readOnly vs long-press: undocumented either way. Keyboard-gating round
  already sets these — watch for interplay in the smoke test.

## Round-1 probe learnings (@baud, 2026-08-16, carry into round 2 whichever route wins)
- touchend must read changedTouches, NOT touches — lifted finger is absent from touches, a
  mouseup forged from touches lands at 0,0 and collapses the range: false negative that mimics
  the exact failure under test.
- Capture-phase click swallower while armed (Bugzilla 1016480: touchend preventDefault does
  not cancel Firefox's synthetic click).
- execCommand copy INLINE and synchronous — any await/setTimeout spends user activation,
  copy silently no-ops. Scratch textarea offscreen via position:fixed + opacity:0, NEVER
  display:none (hidden = unselectable = copies nothing); readOnly + inputMode=none so the
  copy cannot pop a keyboard.
- Native non-passive listeners, not JSX handlers (React delegated/passive — cannot
  preventDefault; same lesson as the wheel round).
- Armed probe disables the pan lane entirely (no taps/scrolls reach the room) — accepted for
  the probe; round 2 must DECIDE this (e.g., drag-selects while vertical-scroll still pans?).
- Probe chip: dashed "sel?", amber when armed, live getSelection strip above chips.
  All blocks headed SMOKE TEST - THROWAWAY for one-pass removal.

## Round-1b findings (2026-08-16 12:25)
- ROUTE 1 CORE ANSWERED YES on the S24: constructed MouseEvents DO drive xterm coordinate
  math in Firefox Android. Remaining question is drop persistence only.
- Probe defects found+fixed: touchcancel was wired to the touchend handler (browser takeover
  indistinguishable from finger lift); contextmenu preventDefault while armed was MISSING
  (Bugzilla 1481923 lane); second touchstart mid-drag forged a new mousedown = SelectionService
  starts a NEW range (wipes drag - looks exactly like the collapse).
- Hypothesis 3 was the instrument itself: readout strip shared a flex column with the terminal;
  selection text growth -> strip +1 line -> terminal shrinks -> ResizeObserver -> fit.fit() ->
  RESIZE DROPS SELECTION, at a repeatable char count. Fixed: strip clipped to fixed height +
  fit HELD during drag, paid out on lift (held count surfaced so data can still kill this).
- Strip now freezes a drop necropsy: DROP at N chars / Mms in / ended-by / touchcancel-menu-
  output-resize-extradown ages+counts. Detector = onSelectionChange (polling would miss drops
  between moves). window error + unhandledrejection listeners armed with the chip.
- ROUND-2 LANE B (door the doc wrongly listed shut): phone app already HAS measured
  pixel-to-cell (reads .xterm-rows box / cols,rows — tmux pane-picking has used it for weeks).
  If forged drags stay unstable: forge only the initial mousedown, track own anchor cell,
  drive range with public select(col,row,len) per move.
- Test protocol: same drag in QUIET room (bare shell) vs LIVE TUI room. Quiet stable + live
  drops = output-clearing. Both drop same = gesture takeover. Strip names it either way.

## Live status (2026-08-16 12:36)
- Round 1b fixes ACCEPTED: "ok much better... I can live with this for now." Selection
  stability parked as good-enough; probe is being promoted, not deleted.
- Left-edge drop root-caused as ANDROID SYSTEM BACK GESTURE (not ours). Option ladder parked,
  no decision: (1) app's existing fullscreen toggle damps edge gestures, (2) phone settings
  (back-gesture sensitivity / right-edge-only), (3) manifest display standalone->fullscreen
  (+ stale manifest text "read-only, in one column" needs refresh), (4) round-2 drag handles
  keep fingers off the raw edge by design.
- PATRICK RULING (standing): BAUD phone gesture surface is terminal scroll + wheel scroll
  ONLY. No future round adds a gesture.
- I-beam relocation SHIPPED + ACCEPTED (Patrick 12:44 "ok its done looks goid and works"):
  view column fullscreen/A+/A-/I-beam, armed = amber + glow + full opacity, sel? string
  zero-count in served bundle (move proved by absence). phone-sEIqr2eW.js.

## Future-parked: thin native wrapper (Patrick 12:40 "gotta build it first lol... good to know")
- WebView shell around the SAME served phone face: web app stays the product (instant server
  deploys unchanged), shell grants OS powers via small bridge - gesture exclusion, mic (kills
  the HTTPS wall, revives STT), real clipboard, immersive, push, biometric token lock.
- Agnostic principle: wrapper = convenience like RC, never load-bearing; browser always works.
- TRIGGER: when 2-3 parked items (mic, edge gestures, copy polish) genuinely block him.

## Proposed rounds (Patrick's go pending)
1. Smoke test (throwaway, on-device): synthetic shift-event selection + execCommand copy.
   Decides Route 1 vs Route 2. ~30 lines behind a temporary chip.
2. Select-mode chip + drag handles + copy button (route per smoke result).
3. Links chip (buffer scan -> tappable sheet). Independent of 1-2, can go any time.
