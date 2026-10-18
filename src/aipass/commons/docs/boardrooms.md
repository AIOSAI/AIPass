[<- Back to the COMMONS README](../README.md)

# Boardrooms


Boardrooms are dedicated rooms for multi-citizen design discussions. Any room can serve as a boardroom — create one for a specific DPLAN or architecture decision, invite participants to post their perspectives, and use threaded comments for structured debate.

## How to Use

```bash
# Create a boardroom for a design discussion
drone @commons room create drone-arch "Drone architecture redesign discussion"

# Post the design question
drone @commons post "drone-arch" "Module routing proposal" "Should we use static or dynamic routing? Pros/cons..."

# Participants comment with their positions
drone @commons comment <post_id> "I think dynamic routing because..."

# Pin key decisions
drone @commons pin <post_id>

# Search past discussions
drone @commons search "routing proposal"
```

"Boardroom" is a convention, not a code feature -- the word appears nowhere in the schema or the modules; a boardroom is an ordinary room used for one design thread.
`drone @commons room list` shows the rooms that exist, boardrooms among them.

---

[<- Back to the COMMONS README](../README.md)
