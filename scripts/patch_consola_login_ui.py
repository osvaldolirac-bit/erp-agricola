#!/usr/bin/env python3
"""Centra el panel de login visible en Super Consola (sin dropdown)."""
from __future__ import annotations

from pathlib import Path

CSS = Path("/root/erp_master/erp_master/static/master.css")
MARKER = ".login-foot {"
INSERT = """
.login-center {
  position: relative;
  z-index: 5;
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1rem 1.25rem 0;
}
.login-panel {
  width: min(360px, 92vw) !important;
  margin: 0 !important;
  padding: 1.35rem 1.25rem 1.15rem !important;
}
.login-panel-head {
  margin-bottom: 0.85rem;
  text-align: center;
}
.login-panel-kicker {
  font-size: 0.72rem;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: #5b6b7c;
}
.login-panel-title {
  margin: 0.15rem 0 0.25rem;
  font-size: 1.35rem;
  font-weight: 800;
  color: #163a5f;
  letter-spacing: -0.02em;
}
.login-panel-sub {
  margin: 0;
  font-size: 0.88rem;
  color: #5b6b7c;
  line-height: 1.35;
}

"""

def main() -> None:
    text = CSS.read_text(encoding="utf-8")
    if ".login-center {" in text:
        print("css: already patched")
        return
    if MARKER not in text:
        raise SystemExit("css marker not found")
    CSS.write_text(text.replace(MARKER, INSERT + MARKER, 1), encoding="utf-8")
    print("css: ok")

if __name__ == "__main__":
    main()
