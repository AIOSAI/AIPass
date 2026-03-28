FROM codercom/code-server:latest

USER root

# Install Python + Node.js (for Claude Code)
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    python3-full \
    alsa-utils \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code (as coder so it's accessible at runtime)
USER 1000
RUN curl -fsSL https://claude.ai/install.sh | bash
USER root
ENV PATH="/home/coder/.local/bin:$PATH"

# Create venv owned by coder user (UID 1000)
RUN python3 -m venv /opt/venv \
    && chown -R 1000:1000 /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Empty workspace — clone your own repo after boot
RUN mkdir -p /home/coder/workspace && chown 1000:1000 /home/coder/workspace

USER 1000
ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8080
ENTRYPOINT ["/usr/bin/entrypoint.sh", "--bind-addr", "0.0.0.0:8080", "--auth", "password", "/home/coder/workspace"]
