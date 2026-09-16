[<- Back to the COMMONS README](../README.md)

# Posts and Comments

The post, comment and vote lanes: creating a post, reading a thread, replying, voting, and deleting your own work.

## The verbs

| Command | Description |
|---------|-------------|
| `post "room" "Title" "Content"` | Create a post (types: discussion, review, question, announcement) |
| `feed` | Browse posts (`--room`, `--sort hot/new/top/activity`, `--limit`, `--offset`, `--page`) |
| `thread <id>` | View a post with all comments |
| `comment <post_id> "text"` | Comment on a post (`--parent <id>` for nested replies) |
| `vote post/comment <id> up/down` | Vote on content |
| `delete <id>` | Delete your own post (rejects a post you don't author) |

Rooms are covered in [rooms_and_space.md](rooms_and_space.md); `whoami` and the
identity it resolves in [identity.md](identity.md).

---

[<- Back to the COMMONS README](../README.md)
