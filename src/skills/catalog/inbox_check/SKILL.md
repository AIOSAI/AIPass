---
name: inbox_check
description: Check ai_mail inbox status across AIPass branches
version: 1.0.0
tags: [communication, mail, status]
requires:
  pip: []
  bins: []
  config: []
has_handler: true
---

# Inbox Check Skill

Scan AIPass branches for `.ai_mail.local/inbox.json` files and report unread message counts. Useful for quickly seeing which branches have pending mail without visiting each one.

## Available Actions

| Action      | Description                                         |
|-------------|-----------------------------------------------------|
| `summary`   | Unread counts per branch (default)                  |
| `all`       | Full message listing for every branch               |
| *branch*    | Show inbox for a specific branch by name            |

## Usage

```bash
drone @skills run inbox_check summary
drone @skills run inbox_check all
drone @skills run inbox_check flow
```

## Output Format

All actions return structured dicts:

```python
{"success": True, "output": "...", "error": None}
```

## Notes

- Reads `.ai_mail.local/inbox.json` from each branch directory
- Messages with `"status": "new"` are counted as unread
- Missing inbox files are silently skipped in summary mode
- No external dependencies -- stdlib only
