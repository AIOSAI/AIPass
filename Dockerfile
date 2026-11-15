# syntax=docker/dockerfile:1
# Build: docker build --build-context repo=.git -t aipass .   (with the release wheel in dist/)
FROM ubuntu:24.04@sha256:786a8b558f7be160c6c8c4a54f9a57274f3b4fb1491cf65146521ae77ff1dc54

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-venv \
    ca-certificates \
    git \
    curl \
    jq \
    nodejs \
    npm \
    bubblewrap \
    tmux \
    ripgrep \
    && rm -rf /var/lib/apt/lists/*

# Claude Code sandboxing needs the sandbox runtime on PATH (plus bwrap above).
# Codex and OpenCode go in before the install, which wires every CLI it finds on PATH.
RUN npm install -g @anthropic-ai/sandbox-runtime @openai/codex@0.169.0 opencode-ai@1.19.5

# The aipass CLI writes its logs beside its own code, so its environment belongs to the user.
RUN useradd -m -s /bin/bash aipass && install -d -o aipass -g aipass /opt/aipass
USER aipass
ENV HOME=/home/aipass
ENV PATH="/home/aipass/.local/bin:/opt/aipass/bin:$PATH"
WORKDIR /home/aipass

RUN curl -fsSL https://claude.ai/install.sh | bash

# The two README steps, done at build: the release wheel, then the install it drives.
RUN --mount=type=bind,source=dist,target=/tmp/wheel \
    python3 -m venv /opt/aipass && /opt/aipass/bin/pip install --no-cache-dir /tmp/wheel/*.whl

# The install clones the commit this image was built from (the repo build context), not whatever
# the public repo holds at build time. The mount is root-owned, hence the one-command safe.directory.
RUN --mount=type=bind,from=repo,target=/src/.git \
    git config --global --add safe.directory '*' \
    && aipass install --non-interactive --yes --no-baud --source /src \
    && git config --global --unset-all safe.directory

CMD ["bash"]
