"""Disable AKTools PyPI version scrape so `/` does not 500 offline.

akfamily/aktools#179: get_latest_version parses pypi.org and crashes when the
markup changed or the container cannot reach PyPI.
"""

from __future__ import annotations

import aktools.utils as aktools_utils


def get_latest_version(package: str = "akshare") -> str:
    return "offline"


aktools_utils.get_latest_version = get_latest_version
