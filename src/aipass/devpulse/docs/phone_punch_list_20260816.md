# Phone face punch list — started 2026-08-16 12:48

GATE OPEN 15:30 — Patrick: "ok ok power on... do ur research full map no questions."
Round structure (devpulse call under no-questions): ROUND A = the card/passport round
(DPLAN-0302 panels + items 9, 12, 13, 14, 15 — one surface, one pass), dispatched first
with the full research map. Remaining items queue for subsequent rounds, one thumb-test
at a time per Patrick's cadence. Rulings made under "no questions": .local button =
"Working Memory" (devpulse rec, twice shown unopposed — display copy, reversible);
passport title = AIPASS over AGENT PASSPORT (his lean + real-passport layout).
ROUND A SHIPPED 15:55 + route-flip 16:05 (bundle phone-B_lckBDt.js): items 9, 12, 13,
14, 15 + DPLAN-0302 panels are BUILT AND DEPLOYED — their bodies below stay as the spec
record. Thumb-test status + fix-up round: see item 13's log. Ship record: DPLAN-0302.

Patrick's rule was: LIST FIRST, no @baud dispatch until it has grown. Items carry his
verbatim words + screenshot refs so the eventual brief needs no reconstruction.
Reference screenshot: /home/patrick/Pictures/BAUD/phone-20260816-124647-3b018d.jpg

## Items (Patrick)

1. BELL COUNT MISSING — "notifications bell nver shows counts. I see them when I open but
   no count." Header bell (PhoneApp.tsx:423 area) renders with no badge; notifications ARE
   there when the sheet opens, so the data lane works and the at-a-glance count is unrendered.
   Needs an unseen-count (cursor vs last-opened, or server count) + badge like the wheel's.

2. GIT COUNT DEAD — "git not cou nting either changes." AgentSheet.tsx:91-98 DOES fetch
   gitChanges per open card; he sees no count. Investigate: fetch failing on phone / rendering
   blank / wrong scope. Data lane exists, so likely client or route bug, not missing feature.

3. CARDS TOO BIG — CLARIFIED 21:13 (phone-20260816-211344-6019f4.jpg): it is the
   FLEET WHEEL. Two defects in the shot: (a) the SELECTED card's label ("devpulse")
   has its bottom clipped by the wheel container — descenders cut, the word half
   covered, caret triangle crowding it; the enlarged selected avatar + label need
   more vertical room than the row gives. (b) Edge cards (commons left, flow right)
   run off-screen with badges/dots clipped — if that is carousel-by-design, the
   clipping should look intentional (fade/peek), not amputated. Brief: give the wheel
   row height that fits the SCALED selected avatar + full label + caret; keep labels
   fully visible for all on-screen cards; edge treatment baud's call (fade or margin).

4. CTRL LABEL BLEED — "ctrl bleeds out of it button boarder." In the key row, the CTRL text
   overflows its key border (visible in screenshot). Same risk: ALT / esc at some widths.
   Same family as baud learning 122: icon/label box must be STATED, not grown from contents.

## Items (devpulse candidates, Patrick to keep or kill)

5. Manifest text stale: "read-only, in one column" + start_url /phone.html — from the
   read-only era; refresh alongside any manifest touch (display:fullscreen option is parked
   in design_touch_selection_links_20260816.md).

6. DEBUG STRIP GOES — Patrick 12:53 "oh the debug can go not needed right." Remove the
   necropsy counters; keep only selection preview + copy action. APPROVED for the round.

7. PLANS VIEW: OPEN PLANS ONLY COUNTED, NOT LISTED — Patrick 12:53 "in plans. it only shows
   closed plan. only list the number of open plans. is that right?" CONFIRMED faithful render:
   the flow dashboard section publishes subjects for recently_closed only + a bare
   active_plans count. TWO-STEP: (a) @flow publishes open-plan list (id+subject) in the
   dashboard section — FLEET-side, dispatch @flow separately; (b) @baud renders it. (b) is
   blocked on (a). Do not put (a) in the baud brief.
   PATRICK SPEC (12:56): 5 newest OPEN by date created (id+subject) + 5 recently closed +
   total open count. Bounded on purpose: "we dont want 22 plans in ur context... we can look
   at old plan any time." Serves BOTH consumers: phone face AND agents' dashboard glance.
   STATUS: @flow half dispatched 12:56. SHIPPED 13:02 (open_recent, 7 red-first tests) +
   surfaced the real offender: flow's active_plans published ALL 23 plan rows — Patrick's
   spec ruled it, cut-to-int dispatched 13:05. @prax refresh clobber seam: one-line fix,
   dispatch @prax AFTER flow's final shape ships. Face renders only after both.
   DATA LANE COMPLETE 13:26: @prax rebuilt refresh to the 5-key contract, 22 tests
   (13 red-first), verified live from devpulse seat. Face render half UNBLOCKED.
   FOR THE BAUD BRIEF: open_recent entries key on `plan_id`, recently_closed on `id`
   (flow 2.0.0 spelling — both writers now identical). total_plans may read 0 on branches
   until flow's next push there (honest-0, self-heals) — face should render 0 gracefully.
   Bonus prax finds: fleet-wide recently_closed misattribution fixed (cards showed OTHER
   branches' closures for months); 7-day closed window now identical across both writers.
   13:37 @flow verified prax's rebuild ON DISK themselves — "face builder brief can drop
   the present-or-absent caveat." open_recent is now guaranteed present. Also fixed:
   central total_closed clobber prax surfaced (zero mismatches, 44 branches).

10. FACE 401 SELF-WIPE TOO TWITCHY — live incident 13:30 today: ONE transient 401 on a
    VALID token (verified fine before and after) made PhoneApp.tsx:288 writeToken(null) +
    signOut — Patrick's session gone, face at the door, "baud is down on phone rn."
    Server-side cause under @api investigation (dispatched 13:43, store-read-during-write
    race suspected). BAUD's half regardless: don't scorch the credential on FIRST 401 —
    re-probe whoami once (short backoff) before wiping; wipe only on a CONFIRMED refusal.
    Related noise: repeated whoami refusals every ~30-90s from the phone even while face
    sat at the door — possible stale service worker (push.ts) or background tab retrying
    with its own dead token copy; worth a look in the same round.
    RESOLUTION NOTE 13:50: door refusals were Patrick pasting a wrong token ("my bad").
    @api INVESTIGATION CLOSED (see DPLAN-0302 riders): their side proven clean, audit
    trail hardened (revoked vs unknown now distinguishable); the 13:30 first 401 is
    unprovable retroactively — stale service-worker token copy is the live suspect,
    which is @baud's half of THIS item. The soften-the-wipe ask stands regardless.

11. TERMINAL SCROLL SPEED SETTING — Patrick 13:51: "add terminal scroll speed to baud
    settings." A speed/sensitivity control for terminal scrolling in BAUD's settings
    (phone finger-scroll is the live context; decide in-round whether desktop wheel
    scroll gets the same knob). Belongs in the interface/gear settings panel alongside
    the existing prefs.

12. TERMINOLOGY RULING: CARDS ARE "PASSPORTS" — Patrick 14:10: "we're gonna refer to
    them as passports in the future. we kind of already do - makes sense." Agent cards =
    passports from now on, face-wide (desktop + phone) in UI copy and our vocabulary.
    Display-level rename first; internal code identifiers can follow later, not required.

13. MANAGER CLASS ON THE PASSPORT + SUB-AGENT ACTIVITY FLASH — Patrick 14:10 (desktop),
    "just an idea... figure out the details later. we just need to highlight that you
    are the manager. helpful for my visibility." Managers/branch owners (devpulse, vera,
    baud) currently only get "a little star on the desktop" — he wants manager-ness ON
    the passport itself: color the CENTER circle, "maybe blue... I don't wanna do red."
    Red-family is reserved for the second half: when an agent is running SUB-AGENTS, the
    middle circle (initials area, e.g. DE) FLASHES to signal it; clicking the passport
    then lists HOW MANY sub-agents are running inside. DATA LANE NOTE — SUPERSEDED by
    DPLAN-0302 research 15:34: the lane ALREADY SHIPS (BranchStatus.subagents,
    types.ts:16, derived in lib.rs) — zero new data was needed, no decision required.
    ROUND A THUMB RESULT 17:23: flash CONFIRMED by Patrick ("i see u went red");
    passport count FAILED — root cause found in code by devpulse: App.tsx:169 holds
    the whole BranchStatus FROZEN at click, PassportView renders subagents from the
    stale object; cards follow the poll, the modal never does. Patrick's ruling on
    the fix pattern: "prax will know how to do this" — the prax monitor is the
    in-app live-follow precedent. Fix-up dispatched to @baud 17:26 (monitor PID
    245440, wd b0om4vfkc): passport follows live poll, check phone AgentSheet for
    same pattern. KNOWN WRINKLE queued, not in scope: backend counts finished
    agents ~3 min (180s agent-file freshness) — count reads N while fewer run.
    17:30 Patrick FYI: "no flash just a solid red" — indicator renders steady,
    spec was flash/pulse. Emailed @baud as addendum to the same round (no 2nd
    wake; they re-check inbox before done). Both land in one deploy.

14. GLOBAL MONITORS MOVE INTO MANAGER PASSPORTS — Patrick 14:10: global prax monitor +
    commons monitor "have their own buttons at the top, but we don't have any room for
    that" — idea: manager-class passports carry the GLOBAL monitor buttons (prax-global,
    commons), "just the way prax monitor works." Every agent's passport keeps its own
    wake + individual prax logs; only managers gain the fleet-wide views. Pairs
    naturally with item 13 (manager-ness visible → manager-only powers live there).

15. IDENTITY SECTION + PASSPORT TITLE — Patrick 14:15: the agent's IDENTITY "should
    also get a card — right in the passport... inside the passport" — render
    passport.json's identity (role, purpose, traits, citizen_class) as its own section/
    tab in the opened passport, joining item 9's Working Memory tabs. AND title the
    document: today the opened card starts bare with the name ("devpulse at the top") —
    above it, name the artifact. His candidates: "AIPass Passport" / "AI Passport"
    (technically AIPass = AI Passport) / "Agent Passport" — leaning AGENT PASSPORT
    ("we do wanna classify the cards as agents - that's what people call them").
    devpulse rec: real-passport layout gives both — issuing authority small then doc
    type large: AIPASS over AGENT PASSPORT, then the name. Bonus flourish for the
    brief: passport.json carries created (e.g. devpulse 2026-03-07) → "Issued" date,
    and registry_id → passport number. The metaphor is already in the data.
    NOTE FOR BRIEF: items 9+12+13+14+15 are one coherent PASSPORT ROUND for @baud.

8. MARKDOWN / HUMAN RENDERING — Patrick 13:08: "markdown rendering to baud for the mail,
   todos, plans and so on. when i user clicks plans a script run I guess and extracts the
   plans section from json and prints show a nice human friendly output." Today these render
   as raw JSON/plain text. Shape: BAUD renders markdown (mail bodies, plan files) and
   pretty-prints structured sections (todos, plans lists) as human cards/lists instead of
   JSON. Client-side rendering in the face; data already flows. Big-ish item — likely its
   own round, maybe split desktop/phone.

9. AGENT CARD MEMORY TABS — Patrick 13:17: "we need to add .local memories, observations
   key learnings tabs to the agent card. so it would just render those section from the
   json, rn it show the whole file right. dash board too maybe. so I user can click
   observation and read jyst the observation right in clean markdown render." Card today
   shows the whole local.json raw. Shape: tabs per section — Sessions / Key Learnings /
   Todos (from local.json) / Observations (observations.json) — each EXTRACTED and rendered
   as clean cards, newest-first, not whole-file JSON. Maybe same treatment for
   DASHBOARD.local.json ("dash board too maybe"). Concrete sub-case of item 8's rendering
   family. ADJACENT to DPLAN-0302: same agent card grows a memory SETTINGS section (limits)
   — these tabs are memory CONTENT. One card area, two panels; the baud brief should land
   them as one coherent memory zone.
   NAMING (RULED under no-questions, see header — "Working Memory", shipped in Round A):
   ".local" button label not descriptive — he floated
   "working memory / tracker / short term". Ruling direction: rename the BUTTON only
   (client-side string, zero risk); full file/system rename = a mission, parked.
   devpulse rec: "Working Memory" — it IS the cognitive term: active window that rolls
   over to long-term (@memory) when full. The architecture already uses the metaphor.

16. TERMINAL BINDS TO THE SEAT, NOT THE PROJECT — BROWSING IS FREE — Patrick 17:47
    RULING, screenshot phone-20260816-174732-3c092f.jpg: baud's passport on the phone
    with EVERY action fenced (resume/fresh/files/shell/watch/settings all greyed)
    behind "baud lives in BAUD — this face reads AIPASS. Switch the project in the
    header to open it." His words (deciphered from dictation): "the terminal is on
    seat not tied to a project. I should be able to have any agent in the terminal
    working chatting... open another project via the project tab drop down, and view
    other agent project files, open any passport and view watch read files. no
    restriction. and if i hit attach resume whatever, it takes over the terminal —
    u are not disturbed. attach is the frictionless switch. what baud has right now
    goes against the flow, we have it setup right on the desktop app."
    SHAPE: two independent bindings. (a) The TERMINAL follows the SEAT — whoever you
    attached to — and survives ALL browsing untouched; only attach/resume re-seats
    it, and that switch is frictionless. (b) BROWSING is project-free: project
    dropdown, any agent's files, any passport, watch/read lanes — no fence, no
    forced project switch. Desktop app = the reference implementation.
    LANE NOTE for the brief: likely splits in two — @baud face half (stop fencing
    the sheet actions to the seated project) and possibly a host half (@api read
    lanes / snapshot feeds may be seated-project-scoped server-side; PassportView's
    own comment says the passport read is "fenced to the seated project"). Decide
    the lane split first, same discipline as items 7/13.

17. DESKTOP FROZEN + TRANSFER ROUND — Patrick 18:43 RULING: "u put mobile arangment
    on desktop. i see. fine, no harm, but dont edit desktop again, we need to
    transfar all u did on desktop to phone now." TWO parts:
    (a) STANDING RULE: desktop face = FROZEN reference. No edits without his
    explicit word — not even drive-by fixes. Desktop is the living spec to copy
    from. (Compass #288 amended; @baud emailed mid-round 18:44.)
    (b) TRANSFER ROUND (next @baud round after the count ships): everything Round A
    built desktop-side gets built PHONE-shaped — the passport document (AIPASS/
    AGENT PASSPORT title block, identity page w/ Issued + passport no., Working
    Memory tabs), monitors in manager sheets, manager marking on the wheel.
    COUNT SHIPPED 18:52 (phone-3jRVJ9AL.js): state line not counter row (doors
    open files, a count is a fact — a dead-door tile teaches doors lie); ZERO
    STATED ("no sub-agents running", self-corrected from render-only-when-news);
    verified 0→1 on the data lane + served bundle. Phone-only, ruling obeyed;
    pre-ruling desktop edits sit uncommitted, untouched, ride the next train.
    PATRICK THUMB 18:55: "looks good red flash and agent count in pasport" —
    the indicator arc (item 13 both halves) is APPROVED on the phone.
    TRANSFER ROUND DISPATCHED 18:57 (PID 268316, wd in flight): parity audit +
    build; lane-check .trinity reads through host files lane BEFORE building
    the document — if blocked, @api gets the lane half, no faked documents.
    TRANSFER SHIPPED 19:11 (phone-CfEZ32z0.js): passport document phone-shaped
    (stacked fields, sideways memory tabs, 6-line clamp), door on the ROW not the
    avatar (mis-tap call), commons monitor live in manager sheets. Ledger corrected
    by their audit: wheel manager mark already existed (FleetWheel:545). Trinity
    reads: LANE OPEN via /v1/files by NAME (absolute paths refused by design —
    desk's verbatim read would always refuse). FIXED on phone: traits array-vs-
    string reader (desk still single-shape, reported, frozen). LANE-BLOCKED: prax
    mission control (watch lane can't express no-target run) — door shipped
    DISABLED with reason, not pointed at prax branch (honest refusal over
    plausible lie). NEW FINDINGS: (a) registry_id IDENTICAL on 6 branches, printed
    as "Passport no." — @spawn's data, Patrick's call label-vs-data; (b) fleet
    lane serves any project but files/dir refuse non-seated = item 16's server
    fence LOCATED+MEASURED. @api dispatched 19:14 (PID 274059): widen read lanes
    per the browse-free ruling + no-target watch shape. Baud's face half queued
    behind it (un-fence elsewhere doors + enable prax door).
    @API SHIPPED 19:24: files/dir/diff serve any census-known project (seat =
    default not fence — one shared 3-line _check_project helper was the whole
    bug, deleted once fixed all three lanes); no-target mission control reachable
    (kind=watch, no branch; empty-string fence kept byte-faithful to baud's
    mirror; labelled watch-all; run-all synonym refused by test). Operate lanes
    untouched. @api queue for later, my word needed: repo_root move post-train;
    THREE project case rules need a fleet ruling (fleet lane case-sensitive,
    verbs insensitive, reads mixed); agent-settings/baud-settings project param
    rides rounds 8-11. BAUD FACE HALF DISPATCHED 19:27 (PID 277824): un-fence
    READ doors only (operate stays seat-fenced — attach takeover is a future
    operate-lane round), enable prax door, one browse-free test pass for Patrick
    with the passport thumb.
    FACE HALF SHIPPED 19:37 (phone-D-oN0YMC.js) + HOST BOUNCED by devpulse 19:38
    (stale PID 237438→280666; baud caught the serving process predating @api's
    code by 3.5h, reported instead of restarting — not their authority). Wire-
    verified by devpulse post-bounce: BAUD README 200/1300B through the foreign
    door, NOPROJECT 503 census sentence, seated 200. Baud's two brief-corrections
    ACCEPTED: watch stays fenced (external watch is @api DESIGN refusal — park
    until Patrick asks, then server-first); agent-settings stays fenced (route
    resolves branch under SEAT — a foreign card's settings door would silently
    EDIT the same-named local agent; catch of the round; project param already
    on @api's rounds-8-11 ledger, baud's damage rationale attached). Monitors
    ride the SEAT by design. ITEM 16 COMPLETE pending Patrick's browse pass.

18. ONE-TERMINAL DOCTRINE — OPERATE LANE UN-FENCE — Patrick 19:51 RULING (pushing
    back on devpulse's reads-now/operate-later split: "when u block u creat
    friction... what is the issue ir reluctance on ur end. desktop does it
    perfectly"): the terminal is A VIEW — one seat hosting whichever agent he
    picks, ANY project, tenant (baud in projects/) or external (vera) — must not
    matter. Attach/resume = the whole switch; wake = how a sleeping agent appears
    in the seat; he runs watchers in aipass OR external projects. Compass #289.
    DISPATCHED @api 19:54 (PID 282245): attach + wake (kill/lock their read) +
    honest external watch (refuse only what genuinely cannot work, e.g. repos
    with no shared prax; tenants like BAUD must watch fine). Operate scope token
    + garbage fences + census refusals all stay — the ruling widens WHO is
    reachable, never what a request may contain. Baud face half follows @api;
    devpulse bounces host on ship (twice-learned). LESSON (compass #289): never
    split a ruled flow into now/later without asking.
    @API SHIPPED 20:03 (red-first in actual order, 9 red, 4/4 mutations): attach
    was NEVER fenced (external door shipped with the attach train — reported
    honestly, not claimed as fix; 3 regression pins added); wake+kill un-fenced,
    project REQUIRED never inferred; watch fence DELETED by measurement (@prax
    states its own scope on screen, better than any fence — @api's anchor-tooling
    rationale was "a guess phrased like expertise, disproved by four probes").
    HOST BOUNCED 20:05 (PID 287774). WAKE MEASURED by devpulse: cross-project
    wake of baud → ok:false @ai_mail sentence; CONFOUND = manager gate (baud is
    manager class; host carries no admin grant). Non-manager case unsettled —
    @ai_mail ruling QUEUED on ledger. BAUD FACE HALF 2 DISPATCHED 20:07 (PID
    288646): open resume/attach/kill/wake/watch doors everywhere, render door
    answers verbatim, settings stays fenced.
    SHIPPED 20:14 (phone-h2_xjWts.js) — baud re-probed @api's watch retraction
    with controls before deleting their fence ("a retraction deserves the same
    verification as a claim"), caught own broken instrument (wrong ws sentinel;
    control failing saved a false report). Verb chips needed NO change (never
    project-fenced). Learning 154 banked: guards outlive their reasons silently.
    20:21 PATRICK REPRO: terminal DROPS on project switch — "nothing changes the
    terminal agent except my hands." ROOT CAUSE (devpulse-traced): PhoneApp:645
    re-resolves every pane's card BY NAME from the SEATED pool per render; seat
    switch → miss → TerminalSheet unmounts → socket closes. Baud's 17:39 latent
    finding promoted live by free browsing. FIX DISPATCHED 20:26 (PID 297349):
    pane lifecycle binds to hands only (attach-swap/end/close), mount-pinned
    sheets never re-consult the live poll, desktop = reference.
    SHIPPED 20:37 (phone-B_uFRA7x.js sha a56c7bf41b8fdd8a1e5560e5, css unchanged,
    pure frontend — no host restart): "THE PANE NO LONGER ASKS THE POLL WHO IT
    IS." Pane holds its card from open time; both "no longer in the fleet read"
    arms DELETED (immunity by absence — no lookup to miss); passport got the same
    held-copy fallback + its self-closing effect removed; unmount = exactly three
    hands (attach swap, end room, tab close). BONUS CATCH: pane keys went
    PROJECT-QUALIFIED (host names rooms baud-project-branch; unqualified keys
    collided same-named agents across projects — wrong pane focused under the
    right name), mission-control key deliberately names nothing (host names
    nothing; a key names what the host names); two HAND-SPELLED template-literal
    keys (silent detach/close breakage waiting) rebuilt through paneKey().
    Verified by absence-at-origin on the served bundle. Baud learning 156 banked:
    latent means fix-it-now when the holder is on the roadmap. Reply-accepted
    (b83edd91 closed). AWAITING PATRICK RELOAD + REPRO: attach devpulse, switch
    header project, browse freely, switch back — chat never blinks.

## 21:04 — Patrick "proceed" → rounds B+ open (pane fix live-thumbed: "I can
## switch and it stays put")

- PREEMPTION: @memory's 20:53 mail found baud's 49 newest key_learnings in a
  wrong schema ({id, learning} vs {number, date, key, value}) — protected ONLY
  by the dated-today guard, which expires at midnight; simulated 08-17 shows
  ids 110-158 (their whole marathon day) trimmed as "oldest history." @baud
  DISPATCHED 21:04 (PID 311783, wd bilynug2m): convert + compress to cap +
  reorder, deadline midnight. @memory's log fix shipped (97 warnings → 1
  summary line + explicit NOTHING DRAINED skip-loop callout, 1077 green);
  their relative-guard proposal (tail-vs-HEAD-date, never expires) ruled ONTO
  their board as scoped red-first piece — fixtures truth-checked first.
- ITEM 2 GIT TILE: @api DISPATCHED 21:04 (live session PID 309485, wd
  b6zd3z81y): read-scope /v1 per-branch git-changes route, desktop transport
  contract, two-door resolve, refusal doctrine, through drone @git. Baud flips
  the NOT_YET entry in a follow-up round. Server bounce is mine after ship.
- SCHEMA REPAIR DONE 21:18 (685s): 49 converted to {number,date,key,value},
  renumbered 112-160 (old ids 110/111 COLLIDED with genuine numbers), max value
  190 chars, array newest-first, zero id/learning remain. Proof = simulation
  both ways against the extractor: before, rollover would archive 95 from tail
  incl. 50 dated tonight; after, keeps 162-148, archives 147 down. Baud widened
  once (named for overrule, ENDORSED): their 61 "correct" entries lacked `key`
  → would vectorize as dict reprs; keys derived from opening clauses, 112/112
  now render key:value through @memory's vectorizer. FOUND NOT FIXED: 21/21 of
  baud's sessions over the 300 cap (max 2529), no status field. ROOT CAUSE
  fleet-grade: baud writes .trinity via python-through-Bash — the PreToolUse
  cap gate NEVER saw a write ("an enforcement I route around is not
  enforcement"). RULED: legacy 21 sessions + 43 over-cap learnings LEFT ALONE
  (vectors keep full text; cap governs the future). Gap goes to @hooks.
- ROUND B DISPATCHED 21:23 (PID 318949, wd byb8m98nb): bell count + CTRL bleed
  + manifest + debug strip (strip GOES, sel chip STAYS) + wheel clipping per
  Patrick's screenshot. Rider: memory-config shape delta heads-up (additive;
  @api killed the scraper; verify renderer before my ONE host bounce, which
  waits for the git-changes route).
- ITEM 2 API HALF SHIPPED 21:29 + HOST BOUNCED 21:33 (287774 → 324804, one
  restart picked up git-changes + memory-config JSON lane; NOTE: server binds
  the TAILSCALE address macbook.taila5c30b.ts.net:8787, NOT loopback — wire
  checks must target it; bounce dropped Patrick's live phone attach sockets,
  one blink, his hands reattach). CONTRACT FOR BAUD'S FLIP: GET
  /v1/git-changes?branch=X&project=Y, read scope → 200 {branch, files
  (branch-local paths), count, untracked}; files+count ARE their GitChanges
  contract unchanged (lib.rs:1070); untracked additive, theirs to ignore;
  400 read_refused unknown branch; 503 read_unavailable drone's sentence.
  Tracked-only semantics MATCH desktop deliberately (diff HEAD --relative).
  WIRE-VERIFIED: seat 200 (devpulse 3 files/2 untracked = my real tree),
  400 named, 503 census sentence. FLIP BRIEF goes to baud after round B.
- FINDINGS FOR PATRICK (from @api, measured): drone verifies callers by
  passport-in-cwd → NO drone-routed lane can measure a FOREIGN project
  (git-changes AND /v1/diff both 503 honestly rather than paint clean).
  Fleet ruling needed to change drone's caller check. PARKED BY PATRICK 21:37
  ("raise a repo iss regarding vera. we deal with later np") → ISSUE #737
  https://github.com/AIOSAI/AIPass/issues/737. Also banked: drone @git status
  --json ask for drone's owner (retires api's porcelain parse).
- ROUND B SHIPPED 21:33 (phone-CqBz3C2x.js da65f2a120c91be1235c2351, css
  CfgVjThN 6ef148f2e5f7b5a5d865d203, manifest 412a4b54f5d6bdf58dfe7066): all
  five + a TWIN (sign-in door said "read-only" — found by a misfired grep,
  method honestly disowned, re-verified properly). Bell marker moves on CLOSE
  (leaving IS the read on a full-height screen), per-project keyed. CTRL row
  flex 1 1 auto + min-content (overflow:hidden REJECTED — a chip reading CTR
  lies about which key it sends). Strip GONE, instrument separated from
  mechanism: forged shift-drag/second-finger/contextmenu/ResizeObserver-hold
  KEPT as fixes; copy+clear kept in plain row while chip armed (judgment call
  ENDORSED — deleting the only copy path deletes the feature). Wheel: scale
  transform doesn't change layout → 11px rail headroom (taken from wrap, net
  ≤2px), label line-height 1.4 (second clipper), 26px edge fade = deliberate
  carousel. Memory-config delta verified field-by-field: no-op except
  refusalGuard would DROP the new suggestion field — wired in round C.
- ROUND C DISPATCHED 21:36 (PID 326387, wd b1cz64qsp): NOT_YET flip for the
  git tile (contract above; foreign projects render 503 honestly, never
  clean/zero) + refusalGuard surfaces suggestion. Host already serving both.
- ROUND C SHIPPED 21:43 (phone-BJBKtYb3.js 0ea7e26919962fdaf83ab7a9, css
  unchanged): BOTH PREMISES DIED TO PROBES. (1) Foreign 503 premise FALSE:
  vera-studio/earmark/aipass-site/marketstand/baud all 200 REAL data (control:
  baud's own tree, count 0/untracked 3 exact); only chess 503s with a TRUE
  "not a git repository". Reconciliation: drone's passport check binds to
  INVOCATION cwd — @api's repro ran drone inside a foreign tree; the server
  invokes from home, target as argument. Issue #737 corrected by comment
  (issuecomment-5311943727), re-scoped, left open for Patrick; @api FYI'd for
  their todo/README re-scope. Tile = three states keyed on the ANSWER (count /
  n/a+server sentence / em-dash for absences) — never on foreignness. (2)
  Baud's own suggestion-drop premise ALSO false (refusals travel 400 through
  errorFrom reading error.message; @api joins the remedy into message at
  memory_config.py:448) — but found+fixed a REAL unreachable bug beside it:
  refusalGuard read body.detail vs envelope's error.message; now reads the
  same fields errorFrom does, suggestion appended only if absent. UNTRACKED
  ruled to the DESKTOP LEDGER (both faces or neither; desktop frozen). Baud
  learnings 166-167 under-cap through the gate. FULL BATCH → Patrick's thumb.
- Item 3 CLARIFIED 21:13 (screenshot): fleet wheel clipping — selected label
  bottom-cut, edge cards amputated. Spec written into item 3 body. Joins the
  next baud round (bell + CTRL + manifest + strip + wheel).

## Scout notes 19:00 — rounds B+ pre-load (read-only sweep, file:line verified)

- Item 1 BELL: phone bell = bare icon, zero state; FeedScreen only mounts when open
  so nothing counts while closed. Desktop Bell.tsx:95-222 is the working pattern
  (poll notificationsRead + clearedUpTo localStorage + badge). notificationsRead IS
  live on the phone transport (transport.http.ts:214). Pure @baud round, no lane.
- Item 2 GIT ROOT CAUSE: transport.http.ts:353 lists git_changes in the NOT_YET
  table → call() throws 501 BEFORE any network request; AgentSheet .catch swallows
  → tile forever "—". NEEDS @API HALF FIRST: a /v1 per-branch git-changes route,
  then ROUTES entry + NOT_YET removal. AgentSheet itself needs no change.
- Item 4 CTRL BLEED: 11 flex-1 equal slots (phone.css:1607-1611) + uppercase
  transform on "ctrl" (css:1633-1640), no overflow rules — longest label in a row
  of 1-2-char glyphs. Trivial CSS fix.
- Item 5 MANIFEST verbatim: name "BAUD — AIPass fleet", description "The AIPass
  fleet, read-only, in one column.", display standalone, start_url /phone.html.
  Stale vs THE COLUMN IS GONE (PhoneApp.tsx:20).
- Item 6 DEBUG STRIP: exact inventory mapped — css 734-791 ("SMOKE TEST -
  THROWAWAY"), TerminalSheet 1416-1454 strip + state 403-438. AMBIGUITY for the
  brief: the sel toggle chip may be permanent (selection stays; strip goes) —
  source comments conflict, rule it in the brief.
- Item 7 PLANS RENDER: ZERO consumption of open_recent/recently_closed/total_plans
  anywhere in the frontend. PLANS tile just opens raw DASHBOARD.local.json in
  CodeMirror. DESIGN DECISION for the brief: client-side parse of the dashboard
  file the tile already opens (no new lane) vs structured host call + types.ts
  fields + a small FeedScreen-pattern section. Bigger than assumed.
- Item 11 SCROLL SPEED: two constants (TerminalSheet LINES_PER_NOTCH=5 :213,
  PAN_ACCELERATION=3 :227, combined :866). Settings plumbing pattern exists
  (BaudSettings types.ts:205-214, bounded()+patch in InterfaceSettings). Thread a
  bounded scroll_sensitivity field down as a prop; constant stays the fallback.
  NOTE: phone consumes NO BaudSettings field today — this would be the first.

## Queue — latent, no misfire today (reported by @baud 17:39, devpulse deferred)

- App.tsx treeBranch holds a whole BranchStatus frozen at click (same species as the
  passport bug). FileTree reads only identity fields today — freezes the day anyone
  renders a live field there. Fix = same identity-pattern lookup, any future round.
- phone/PhoneApp.tsx resolves an open pane's card by NAME ONLY while the rest of that
  face is project-qualified via cardRef. Safe today (panes search seated project only);
  the one unqualified lookup on the phone face.
- Deliberate mount-pins that STAY: MonitorSheet + TerminalSheet pin branch at mount for
  written-down reasons (re-spawned watch / retyped launch line every 10s). Correct as-is.
- 17:47 FIX-UP SHIPPED (@baud): passport follows live poll (identity pattern, name AND
  project, snapshot only as gone-branch fallback; phone AgentSheet never had the bug —
  cardRef pattern). Indicator now PULSES: animation was running but INVISIBLE (35%-alpha
  halo next to solid red disc); disc now fills/inverts 1.3s, phone wheel avatar fixed
  same round, reduced-motion holds the filled disc. Desktop binary rebuilt — RELAUNCH
  NEEDED. Bonus settled on the wire: @api 200-ok-false species REAL (unknown branch
  after routing) → @api dispatched to unify to 400 memory_config_refused.
- 17:55 @api SHIPPED the unification: 400 everywhere incl. /push which had NO refusal
  path at all (every refused fleet reset returned 200 — worst instance, self-found).
  10 red-first tests, 4/4 mutations. ok field KEPT inert for @baud's live guard —
  retire coordinated later, written down both sides. FPLAN-0430 closed.
- 18:37 REFRAME (Patrick: "we are on the phone ?? not desktop"): he thumbed from the
  PHONE all evening. Phone face renders NO sub-agent count anywhere (grep: one hit,
  FleetWheel busy class only) — the count line lives in desktop PassportView alone.
  His "no agent count" was a missing feature on his device, not the frozen modal
  (that bug was real but desktop-only; devpulse assumed desktop — wrong). Pulse fix
  DID reach the phone (wheel avatar CSS) — page reload gets it. Count round
  dispatched @baud 18:38 (PID 258205): render subagents in AgentSheet, live for
  free via cardRef.
