"""Tiny shared HTTP transport (stdlib only). Returns (status, body, lower-cased headers)."""

from __future__ import annotations

import gzip
import urllib.error
import urllib.request


def _unpack(status: int, body: bytes, headers) -> tuple:
    lowered = {k.lower(): v for k, v in headers.items()}
    if lowered.get("content-encoding") == "gzip":
        body = gzip.decompress(body)
    return status, body, lowered


def urllib_get(url: str, headers: dict) -> tuple:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as resp:  # SPARQL can take up to 60 s
            return _unpack(resp.status, resp.read(), resp.headers)
    except urllib.error.HTTPError as err:  # non-2xx still carries a status the caller handles
        return _unpack(err.code, err.read(), err.headers)
