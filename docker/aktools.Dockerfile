# Local AKTools HTTP sidecar. Official aktools:1.8.95 freezes akshare at 1.8.94,
# which rejects A-share codes like 000001 ("请升级 AKShare"). Build once;
# do not pip-upgrade on every compose up.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/aktools-patch \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=10

RUN pip install \
    -i https://mirrors.aliyun.com/pypi/simple/ \
    --trusted-host mirrors.aliyun.com \
    "akshare>=1.16" \
    "aktools>=0.0.89" \
    "fastapi>=0.115.5,<0.116" \
    "starlette>=0.40,<1"

COPY aktools_sitecustomize.py /opt/aktools-patch/sitecustomize.py

EXPOSE 8080
CMD ["python", "-m", "aktools", "--host", "0.0.0.0", "--port", "8080"]
