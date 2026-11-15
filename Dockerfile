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
RUN npm install -g @anthropic-ai/sandbox-runtime

# The image holds exactly the wheel the release built: the build context is dist/*.whl and nothing else.
COPY dist/*.whl /tmp/wheel/
RUN python3 -m venv /opt/aipass \
    && /opt/aipass/bin/pip install --no-cache-dir /tmp/wheel/*.whl \
    && rm -rf /tmp/wheel

RUN useradd -m -s /bin/bash aipass
USER aipass
ENV HOME=/home/aipass
ENV PATH="/home/aipass/.local/bin:/opt/aipass/bin:$PATH"
RUN curl -fsSL https://claude.ai/install.sh | bash

WORKDIR /home/aipass
CMD ["bash"]
