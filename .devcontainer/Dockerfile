FROM mcr.microsoft.com/devcontainers/python:1-3.11-bookworm

# Node.js is required for Claude Code's npm distribution.
ARG NODE_MAJOR=22
# The base image's Yarn apt repo has an expired signing key and breaks
# `apt-get update`. Yarn isn't needed here, so drop that source.
RUN rm -f /etc/apt/sources.list.d/yarn*.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_${NODE_MAJOR}.x nodistro main" > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Pre-create the Claude config dir so the named volume mounted here
# inherits vscode ownership instead of being created as root.
RUN mkdir -p /home/vscode/.claude && chown -R vscode:vscode /home/vscode/.claude

USER vscode
