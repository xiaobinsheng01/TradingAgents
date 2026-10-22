FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=10

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /build
# Install deps before the full tree so code-only edits reuse this layer.
COPY pyproject.toml README.md ./
COPY tradingagents/ tradingagents/
COPY cli/ cli/
COPY web/ web/
# Same Aliyun index as docker/aktools.Dockerfile. PyPI via the host proxy stalls.
RUN pip install --no-cache-dir \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    ".[web]"
COPY . .

FROM nginx:alpine AS frontend

COPY --from=builder /build/web/static /usr/share/nginx/html
COPY web/nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER=WEB_API_UPSTREAM \
    WEB_API_UPSTREAM=web-api:8000
EXPOSE 80

FROM python:3.12-slim AS backend

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN useradd --create-home appuser \
 && install -d -m 0755 -o appuser -g appuser /home/appuser/.tradingagents
USER appuser
WORKDIR /home/appuser/app

COPY --from=builder --chown=appuser:appuser /build .

ENTRYPOINT ["tradingagents"]
