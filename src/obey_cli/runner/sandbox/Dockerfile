# Default obey sandbox: Python, Node, Go, git and the headless agent CLIs, run as a non-root user.
# Build: obey doctor --build-image   (or: docker build -t obey-sandbox:<version> <this directory>)
ARG GO_IMAGE=golang:1.27.3-trixie
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.12.9
FROM ${GO_IMAGE} AS go
FROM ${UV_IMAGE} AS uv

FROM node:24.22.1-trixie-slim
ARG CLAUDE_CODE_VERSION=
ARG CODEX_VERSION=
ARG OPENCODE_VERSION=
ARG GEMINI_CLI_VERSION=
ARG COPILOT_CLI_VERSION=
ARG PNPM_VERSION=9.15.9
ENV DEBIAN_FRONTEND=noninteractive \
    PATH=/usr/local/go/bin:/home/agent/.local/bin:$PATH \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0 \
    NPM_CONFIG_UPDATE_NOTIFIER=false \
    PIP_DISABLE_PIP_VERSION_CHECK=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates python3 python3-venv python3-pip ripgrep \
    procps less jq patch make \
 && rm -rf /var/lib/apt/lists/* \
 && usermod -l agent -d /home/agent -m node && groupmod -n agent node
COPY --from=go /usr/local/go /usr/local/go
COPY --from=uv /uv /uvx /usr/local/bin/
RUN corepack enable && corepack prepare "pnpm@${PNPM_VERSION}" --activate \
 && set -e; pkgs=""; \
    [ -n "$CLAUDE_CODE_VERSION" ] && pkgs="$pkgs @anthropic-ai/claude-code@$CLAUDE_CODE_VERSION"; \
    [ -n "$CODEX_VERSION" ] && pkgs="$pkgs @openai/codex@$CODEX_VERSION"; \
    [ -n "$OPENCODE_VERSION" ] && pkgs="$pkgs opencode-ai@$OPENCODE_VERSION"; \
    [ -n "$GEMINI_CLI_VERSION" ] && pkgs="$pkgs @google/gemini-cli@$GEMINI_CLI_VERSION"; \
    [ -n "$COPILOT_CLI_VERSION" ] && pkgs="$pkgs @github/copilot@$COPILOT_CLI_VERSION"; \
    if [ -n "$pkgs" ]; then npm install -g --omit=dev $pkgs && npm cache clean --force; fi
COPY entrypoint.sh /usr/local/bin/obey-entrypoint
RUN chmod 755 /usr/local/bin/obey-entrypoint && mkdir -p /home/agent/work && chown -R agent:agent /home/agent
USER agent
WORKDIR /home/agent/work
ENTRYPOINT ["/usr/local/bin/obey-entrypoint"]
