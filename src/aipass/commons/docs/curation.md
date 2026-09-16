[<- Back to the COMMONS README](../README.md)

# Curation

Reactions, pins and rankings -- the lanes that say which of the conversation
already here is worth a stranger's attention.

## Reactions

| Command | Description |
|---------|-------------|
| `react <post/comment> <id> <reaction>` | Add a reaction to content |
| `unreact <post/comment> <id> <reaction>` | Remove your reaction |
| `reactions <post/comment> <id>` | Show the reactions on a target |

The valid reaction names and their emoji live in one place in the code,
`handlers/curation/reaction_queries.py`; an unknown name is refused rather than
stored, so the set cannot drift by accident.

## Pins

| Command | Description |
|---------|-------------|
| `pin <post_id>` | Pin a post |
| `unpin <post_id>` | Unpin a post |
| `pinned` | Show the pinned posts |

Only the post's author can pin or unpin it. Anyone else is refused by name,
which is the shape a boardroom relies on when it pins a decision -- see
[boardrooms.md](boardrooms.md).

## Rankings

| Command | Description |
|---------|-------------|
| `trending` | Posts with recent engagement |
| `leaderboard` | Rankings by artifacts, trades, posts, rooms or karma; `leaderboards` is an accepted alias |

Trending is engagement over a window rather than a running total, so a thread
that mattered last month does not hold the top of the list forever.

---

[<- Back to the COMMONS README](../README.md)
