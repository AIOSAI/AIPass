# {plan_number}: {subject}

Tag: research, {tag}

> One-line summary: what is studied + the question the research answers

---

## What is an RPLAN?

Research Plans (RPLANs) hold **research of any kind** -- work whose output is understanding, not code. An RPLAN is the artifact that makes research recoverable next session.

**This is for:**
- Tracing our own code -- following a flow, a dispatch path, a bug to its source
- Studying an external repo or pip package -- architecture, patterns, design decisions
- Comparing approaches, tools, or implementations side by side
- Measuring something -- timings, sizes, counts, behavior under load
- Recording honest assessments -- what holds up, what does not, what matters
- Preserving research so it is not repeated next session

**This is NOT for:**
- Building code -- that is an FPLAN
- Designing a feature -- that is a DPLAN (create one when research inspires a build)
- Quick glances -- if it takes 5 minutes, a note in memories is enough

**Where an RPLAN lives:** internal research lives in the branch doing the research. When the subject is an external checkout, the RPLAN lives in that external repo's root directory, so the research is right there on the next visit.

**Never trim RPLAN.** Raw findings, dead ends, "this looked promising but wasn't" -- all valuable. Future you will thank past you.

---

## Source

| Field | Value |
|-------|-------|
| **Subject** | Repo, package, or our own area (name + URL or path) |
| **Version or commit analyzed** | Version number or commit hash |
| **Question** | What the research must answer |
| **Method** | Read-only rules followed, sub-agents used and what each covered |
| **Brief** | Path to the brief given to sub-agents |
| **Report** | Path to the report(s) returned |
| **Spot-checks** | What the plan's owner verified directly from its own seat |

## What It Does

High-level description of the subject. What problem does it solve? Who is it for? How does it work conceptually? For an internal trace, what the traced flow is meant to do.

## Architecture

How the subject is structured. Key directories, entry points, data flow, call paths. Include a tree or diagram when it helps.

```
project/
├── core/          # What lives here
├── clients/       # What lives here
└── integrations/  # What lives here
```

## Key Files Analyzed

Each significant file reviewed:

### filename.py (LOC count)
- **Purpose:** What it does
- **Core pattern:** Main approach or algorithm
- **What's notable:** Design decisions, clever or questionable
- **Relevance:** How this informs the question
- **Gotchas:** Limitations or issues noticed

*(Repeat for each file worth documenting)*

## Findings

What the research found. Be specific -- not "their memory is good" but "they use prefix-indexed keys like AGENT:id:STATE:type for O(k) queries, which could improve our ChromaDB tagging." A finding is whatever the research turned up: a pattern worth adopting, a bug, a gap, a measurement, a confirmed behavior.

| Finding | Where | What it changes | Priority |
|---------|-------|-----------------|----------|
| Example finding | file.py:line | What it means for us or what it fixes | High/Med/Low |

## Patterns to Avoid

What not to copy or repeat. Bad practices, overcomplicated approaches, things that do not fit our architecture.

## Honest Assessment

- **What works well:**
- **What does not:**
- **Overlap with AIPass:**
- **Key differentiator or root cause:**

## Next Steps

- [ ] Create a DPLAN or FPLAN for any finding worth building or fixing
- [ ] Note findings in relevant branch memories
- [ ] Share with relevant branches via dispatch if applicable

## Relationships
- **Related plans:** Design or build plans this research informs or inspired
- **Related branches:** Which AIPass branches are affected or benefit
- **Discovered via:** How the subject came up (recommendation, search, dependency, incident, etc.)

## Notes
Session notes, raw observations, things noticed during research

## Listen (TTS-friendly summary)

Write a plain English summary of this research here. No markdown, no symbols, no tables, no code blocks, no asterisks, no bullet points. Just natural sentences that can be read aloud by a text to speech tool. Cover what was studied, what the research found, and what it changes for AIPass.

---
*Created: {today}*
*Updated: {today}*
