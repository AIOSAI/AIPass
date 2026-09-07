# Dropbox

Inbound-only mailbox for `{{BRANCHNAME}}`.

Other branches place files here for `{{BRANCHNAME}}` to consume once, then move
out or delete.

Not an outbox: this branch's own deliverables to others live in `docs.local/`
until sent. Not an archive either — anything meant to persist as a durable
record belongs in `docs.local/`, or in a tracked `docs/` file, rather than
accumulating here.
