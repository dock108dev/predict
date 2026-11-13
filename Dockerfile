FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv
FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b AS dependencies
WORKDIR /predict
ENV UV_PYTHON_DOWNLOADS=never UV_NO_CACHE=1
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra stream --no-install-project

FROM python:3.14-slim-bookworm@sha256:3fe1a0b6c2d6b2ebb572906cdabeca75aeb558c0c17db5ffefbcf8094871c32b
WORKDIR /predict
ENV PATH=/predict/.venv/bin:$PATH PYTHONPATH=/predict PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN mkdir -p /predict/.local && chown 10001:10001 /predict/.local
COPY --from=dependencies /predict/.venv .venv
COPY app app
COPY deploy/check-health.py deploy/check-health.py
COPY scripts/live_coverage_census.py scripts/pipeline_storage_report.py scripts/sgo_runtime_census.sql scripts/
USER 10001:10001
CMD ["python", "-m", "app.dashboard.opportunity_board", "--host", "0.0.0.0", "--port", "8784"]
