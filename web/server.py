"""Uvicorn entry for the local web console.

Host binds stay loopback unless TRADINGAGENTS_WEB_BIND_ALL is set so a
container can listen on 0.0.0.0 for compose networking. Publish host ports
as 127.0.0.1, not 0.0.0.0.
"""

from __future__ import annotations

import os

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})
DOCKER_INTERNAL_HOSTS = frozenset({"0.0.0.0", "::", "[::]"})


def _bind_all_enabled() -> bool:
    return os.environ.get("TRADINGAGENTS_WEB_BIND_ALL", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def assert_loopback_host(host: str) -> None:
    """Refuse LAN/public binds. Docker-internal 0.0.0.0 needs BIND_ALL."""
    normalized = host.strip().lower()
    if normalized in LOOPBACK_HOSTS:
        return
    if normalized in DOCKER_INTERNAL_HOSTS and _bind_all_enabled():
        return
    raise RuntimeError(
        f"Refusing to bind {host!r}. The web console is loopback-only "
        "(use 127.0.0.1). Inside Docker, set TRADINGAGENTS_WEB_BIND_ALL=1 "
        "and publish 127.0.0.1 on the host."
    )


def run_web_console(
    host: str = "127.0.0.1",
    port: int = 8000,
    *,
    serve_frontend: bool = True,
) -> None:
    assert_loopback_host(host)
    import uvicorn

    from web.app import create_app

    uvicorn.run(
        create_app(serve_frontend=serve_frontend),
        host=host,
        port=port,
        log_level="info",
        timeout_keep_alive=75,
    )
