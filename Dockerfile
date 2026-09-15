# Kestrel: supply-chain simulator, desk API and model player.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --all-extras --no-install-project
COPY kestrel ./kestrel
COPY frontend ./frontend
RUN uv sync --frozen --no-dev --all-extras
EXPOSE 8000
# Desk + API. For the model CLI: docker run --rm -e OPENROUTER_API_KEY=... -v $PWD/runs:/app/runs kestrel uv run python -m kestrel.agent run --task red_sea --player rule
CMD ["uv", "run", "--no-sync", "uvicorn", "kestrel.api:app", "--host", "0.0.0.0", "--port", "8000"]
