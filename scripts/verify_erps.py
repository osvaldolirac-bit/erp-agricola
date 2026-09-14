#!/usr/bin/env python3
"""Verifica ERP Constructora (:8509) y GlobalGAP (/agricola/globalgap)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

CONSTRUCTORA = os.environ.get("CONSTRUCTORA_URL", "http://127.0.0.1:8509").rstrip("/")
GLOBALGAP_BASE = os.environ.get("GLOBALGAP_BASE", "https://erpmaster.cl/agricola/globalgap").rstrip("/")
GG_EMAIL = os.environ.get("VERIFY_GLOBALGAP_EMAIL", "osvaldolirac@gmail.com")
GG_PASSWORD = os.environ.get("VERIFY_GLOBALGAP_PASSWORD", "Erpmaster2026")


class CheckFailed(Exception):
    pass


def http(method: str, url: str, data: dict | None = None, headers: dict | None = None):
    body = None
    hdrs = dict(headers or {})
    if data is not None:
        body = urllib.parse.urlencode(data).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/x-www-form-urlencoded")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def check_constructora() -> None:
    code, _, _ = http("GET", f"{CONSTRUCTORA}/login")
    if code != 200:
        raise CheckFailed(f"constructora login HTTP {code}")
    print("OK  constructora login")


def check_globalgap_public() -> None:
    code, _, body = http("GET", f"{GLOBALGAP_BASE}/login")
    if code != 200:
        raise CheckFailed(f"globalgap login HTTP {code}")
    if b"GlobalGAP" not in body and b"globalgap" not in body.lower():
        raise CheckFailed("globalgap login page unexpected content")
    print("OK  globalgap login page")


def check_globalgap_auth() -> None:
    if not GG_PASSWORD:
        print("SKIP globalgap auth (no VERIFY_GLOBALGAP_PASSWORD)")
        return
    jar = urllib.request.HTTPCookieProcessor()
    opener = urllib.request.build_opener(jar)
    post = urllib.request.Request(
        f"{GLOBALGAP_BASE}/login",
        data=urllib.parse.urlencode(
            {"email": GG_EMAIL, "password": GG_PASSWORD}
        ).encode("utf-8"),
        method="POST",
    )
    post.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp = opener.open(post, timeout=25)
        code = resp.status
        resp.read()
    except urllib.error.HTTPError as exc:
        code = exc.code
    if code not in (200, 302):
        raise CheckFailed(f"globalgap POST login HTTP {code}")
    panel = urllib.request.Request(f"{GLOBALGAP_BASE}/panel")
    try:
        presp = opener.open(panel, timeout=25)
        pcode = presp.status
        pbody = presp.read()
    except urllib.error.HTTPError as exc:
        pcode = exc.code
        pbody = exc.read()
    if pcode != 200:
        raise CheckFailed(f"globalgap panel HTTP {pcode}")
    if b"Consultor" not in pbody and b"Panel" not in pbody:
        raise CheckFailed("globalgap panel unexpected content")
    print("OK  globalgap login + panel")


def main() -> int:
    failed = 0
    for fn in (check_constructora, check_globalgap_public, check_globalgap_auth):
        try:
            fn()
        except CheckFailed as exc:
            print(f"FAIL {fn.__name__}: {exc}", file=sys.stderr)
            failed += 1
        except Exception as exc:
            print(f"FAIL {fn.__name__}: {exc}", file=sys.stderr)
            failed += 1
    if failed:
        print(f"\n{failed} ERP check(s) failed", file=sys.stderr)
        return 1
    print("\nAll ERP checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
