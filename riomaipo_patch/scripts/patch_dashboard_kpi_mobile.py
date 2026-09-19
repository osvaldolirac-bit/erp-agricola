#!/usr/bin/env python3
"""Dashboard KPIs: 2 por fila en móvil + colores ingresos/egresos."""
from __future__ import annotations

import re
import shutil
from pathlib import Path

ROOT = Path("/root/riomaipo/rmweb")
CSS = ROOT / "static" / "css" / "app.css"
DASH = ROOT / "templates" / "dashboard.html"
SRC_DASH = Path(__file__).resolve().parents[1] / "rmweb" / "templates" / "dashboard.html"
BASE = ROOT / "templates" / "base.html"

OLD_KPI_BLOCK = """\
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: .65rem;
  margin-bottom: 1rem;
}
.kpi-grid.kpi-grid-6 {
  grid-template-columns: repeat(6, minmax(0, 1fr));
}
a.kpi { display: block; color: #fff; }
a.kpi:hover { color: #fff; filter: brightness(1.05); }
@media (max-width: 1100px) {
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sidebar { width: 210px; }
}
@media (max-width: 760px) {
  .app-shell { flex-direction: column; }
  .sidebar { width: 100%; height: auto; position: relative; }
  .kpi-grid { grid-template-columns: 1fr; }
}
.kpi {
  border-radius: 12px;
  padding: .85rem .95rem;
  color: #fff;
  min-height: 92px;
  box-shadow: 0 8px 22px rgba(22,58,95,.12);
}
.kpi .label { font-size: .78rem; font-weight: 700; opacity: .95; }
.kpi .value { font-size: 1.12rem; font-weight: 800; margin-top: .35rem; }
.kpi .hint { font-size: .78rem; margin-top: .25rem; opacity: .9; }
.kpi.blue { background: linear-gradient(135deg, #1f4b99, #2f6fed); }
.kpi.cyan { background: linear-gradient(135deg, #0f8fa8, #22b8cf); }
.kpi.pink { background: linear-gradient(135deg, #c23a6b, #e85d8a); }
.kpi.green { background: linear-gradient(135deg, #1f8a65, #2fbf71); }
.kpi.orange { background: linear-gradient(135deg, #c46a12, #f0a202); }
"""

# Also match if previous patch already removed kpi-grid-6 6-col but left 5-col base
OLD_KPI_BLOCK_ALT = """\
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: .65rem;
  margin-bottom: 1rem;
}
a.kpi { display: block; color: #fff; }
a.kpi:hover { color: #fff; filter: brightness(1.05); }
@media (max-width: 1100px) {
  .kpi-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sidebar { width: 210px; }
}
@media (max-width: 760px) {
  .app-shell { flex-direction: column; }
  .sidebar { width: 100%; height: auto; position: relative; }
  .kpi-grid { grid-template-columns: 1fr; }
}
.kpi {
  border-radius: 12px;
  padding: .85rem .95rem;
  color: #fff;
  min-height: 92px;
  box-shadow: 0 8px 22px rgba(22,58,95,.12);
}
.kpi .label { font-size: .78rem; font-weight: 700; opacity: .95; }
.kpi .value { font-size: 1.12rem; font-weight: 800; margin-top: .35rem; }
.kpi .hint { font-size: .78rem; margin-top: .25rem; opacity: .9; }
.kpi.blue { background: linear-gradient(135deg, #1f4b99, #2f6fed); }
.kpi.cyan { background: linear-gradient(135deg, #0f8fa8, #22b8cf); }
.kpi.pink { background: linear-gradient(135deg, #c23a6b, #e85d8a); }
.kpi.green { background: linear-gradient(135deg, #1f8a65, #2fbf71); }
.kpi.orange { background: linear-gradient(135deg, #c46a12, #f0a202); }
"""

NEW_KPI_BLOCK = """\
.kpi-grid,
.kpi-grid.kpi-grid-2,
.kpi-grid.kpi-grid-6 {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: .65rem;
  margin-bottom: 1rem;
}
a.kpi { display: block; color: #fff; }
a.kpi:hover { color: #fff; filter: brightness(1.05); }
@media (max-width: 1100px) {
  .kpi-grid,
  .kpi-grid.kpi-grid-2,
  .kpi-grid.kpi-grid-6 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .sidebar { width: 210px; }
}
@media (max-width: 760px) {
  .app-shell { flex-direction: column; }
  .sidebar { width: 100%; height: auto; position: relative; }
  .kpi-grid,
  .kpi-grid.kpi-grid-2,
  .kpi-grid.kpi-grid-6 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: .5rem;
  }
  .kpi { min-height: 84px; padding: .7rem .75rem; }
  .kpi .label { font-size: .68rem; line-height: 1.2; }
  .kpi .value {
    font-size: .95rem;
    word-break: break-word;
    overflow-wrap: anywhere;
  }
  .kpi .hint { font-size: .68rem; }
}
.kpi {
  border-radius: 12px;
  padding: .85rem .95rem;
  color: #fff;
  min-height: 92px;
  box-shadow: 0 8px 22px rgba(22,58,95,.12);
}
.kpi .label { font-size: .78rem; font-weight: 700; opacity: .95; }
.kpi .value { font-size: 1.12rem; font-weight: 800; margin-top: .35rem; }
.kpi .hint { font-size: .78rem; margin-top: .25rem; opacity: .9; }
/* Legacy */
.kpi.blue { background: linear-gradient(135deg, #1f4b99, #2f6fed); }
.kpi.cyan { background: linear-gradient(135deg, #0f8fa8, #22b8cf); }
.kpi.pink { background: linear-gradient(135deg, #c23a6b, #e85d8a); }
.kpi.green { background: linear-gradient(135deg, #1f8a65, #2fbf71); }
.kpi.orange { background: linear-gradient(135deg, #c46a12, #f0a202); }
/* Semántica ingresos / egresos */
.kpi.kpi-info { background: linear-gradient(135deg, #1f4b99, #2f6fed); }
.kpi.kpi-ingreso { background: linear-gradient(135deg, #1f8a65, #2fbf71); }
.kpi.kpi-egreso { background: linear-gradient(135deg, #b42318, #e04b3a); }
.kpi.kpi-alerta { background: linear-gradient(135deg, #c46a12, #f0a202); }
.kpi.kpi-alerta-egreso { background: linear-gradient(135deg, #8f1d4a, #d63b6a); }
"""


def main() -> int:
    if not SRC_DASH.exists():
        raise SystemExit(f"FAIL: missing {SRC_DASH}")

    css = CSS.read_text(encoding="utf-8")
    if "kpi-grid-2" in css and "kpi-alerta-egreso" in css and "repeat(2, minmax(0, 1fr))" in css and "grid-template-columns: 1fr;" not in css.split(".kpi-grid")[1][:800]:
        # still may need to fix 1fr mobile if already partially patched
        pass

    if "kpi-alerta-egreso" in css and ".kpi-grid.kpi-grid-2" in css and "grid-template-columns: 1fr;" not in re.search(
        r"@media \(max-width: 760px\) \{.*?\}", css, re.S
    ).group(0):
        print("css already patched")
    else:
        shutil.copy2(CSS, CSS.with_suffix(".css.bak_kpi2"))
        if OLD_KPI_BLOCK in css:
            css = css.replace(OLD_KPI_BLOCK, NEW_KPI_BLOCK, 1)
        elif OLD_KPI_BLOCK_ALT in css:
            css = css.replace(OLD_KPI_BLOCK_ALT, NEW_KPI_BLOCK, 1)
        else:
            # Fallback: replace from .kpi-grid through .kpi.orange block
            m = re.search(
                r"\.kpi-grid \{.*?\.kpi\.orange \{[^}]+\}",
                css,
                re.S,
            )
            if not m:
                raise SystemExit("FAIL: kpi CSS block not found")
            css = css[: m.start()] + NEW_KPI_BLOCK + css[m.end() :]
        CSS.write_text(css, encoding="utf-8")
        print("OK app.css")

    shutil.copy2(DASH, DASH.with_suffix(".html.bak_kpi2"))
    shutil.copy2(SRC_DASH, DASH)
    print("OK dashboard.html")

    # Cache-bust stylesheet for iPhone Safari
    base = BASE.read_text(encoding="utf-8")
    new_link = '<link href="{{ url_for(\'static\', filename=\'css/app.css\') }}?v=kpi2" rel="stylesheet">'
    old_link = '<link href="{{ url_for(\'static\', filename=\'css/app.css\') }}" rel="stylesheet">'
    old_link_v = re.compile(
        r'<link href="\{\{ url_for\(\'static\', filename=\'css/app\.css\'\) \}\}(?:\?v=[^"]*)?" rel="stylesheet">'
    )
    if "?v=kpi2" in base:
        print("base.html cache already kpi2")
    else:
        shutil.copy2(BASE, BASE.with_suffix(".html.bak_kpi2"))
        if old_link in base:
            base = base.replace(old_link, new_link, 1)
        else:
            base, n = old_link_v.subn(new_link, base, count=1)
            if n != 1:
                raise SystemExit("FAIL: app.css link not found in base.html")
        BASE.write_text(base, encoding="utf-8")
        print("OK base.html cache-bust")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
