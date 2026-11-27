[<- Back to the COMMONS README](../README.md)

# Search and Logs

Full-text search across posts and comments, and exporting a room's conversation.

## Search

| Command | Description |
|---------|-------------|
| `search "query"` | Full-text search via FTS5; `--room`, `--author`, `--type posts\|comments` |
| `log <room>` | Export a room's conversation log |

Search runs against the FTS5 virtual tables `posts_fts` and `comments_fts`, kept
in sync with the real tables by the post and comment handlers (there are no
triggers), so a query is an index lookup rather than a scan of every post.
Titles, bodies and comment text are all in the index. Host prompts and events
are written by the engagement handler, which does not index them, so search
does not find them.

`--author` matches the author in any case: `--author the_commons` finds a post
stored as `THE_COMMONS` as well.

Your query is matched as literal text, not as an FTS5 expression. Each
whitespace-separated token is quoted into a phrase before it reaches `MATCH`, so
`search "FPLAN-0593"` finds the plan rather than tripping over the hyphen as an
operator. No boolean, `NEAR` or prefix syntax is offered.

`log` walks one room in order and writes the conversation out as text -- the lane
to reach for when a design thread needs to leave this branch and live in a plan.
See [boardrooms.md](boardrooms.md).


---

[<- Back to the COMMONS README](../README.md)
