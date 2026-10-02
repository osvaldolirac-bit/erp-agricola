#!/usr/bin/env python3
"""Restaura super_consola con sidebar (_base_app) + prorrateo ha + flags Espino."""
from __future__ import annotations

import sys
from pathlib import Path

SOURCE = Path(
    sys.argv[1]
    if len(sys.argv) > 1
    else "/root/erp_master/erp_master/templates/super_consola.html.bak_extender_20260805130840"
)
TARGET = Path(
    sys.argv[2]
    if len(sys.argv) > 2
    else "/root/erp_master/erp_master/templates/super_consola.html"
)

OLD_PRORRATEO = """      {% if sec == 'prorrateo' and prorrateo %}
      <section class="admin-block">
        <h3>Prorrateo CC</h3>
        <p class="help">
          Porcentajes de imputación de <strong>costos fijos</strong> (sueldos / RRHH y otros gastos prorrateados del campo).
          Deben sumar <strong>100 %</strong>.
          {% if prorrateo.directos %}
          Fuera de este reparto (imputación directa): <strong>{{ prorrateo.directos|join(', ') }}</strong>.
          {% endif %}
          Aplica a movimientos nuevos; no recalcula históricos.
        </p>
        <form method="post" class="form-grid">
          <input type="hidden" name="action" value="prorrateo_guardar">
          <input type="hidden" name="sec" value="prorrateo">
          {% for r in prorrateo.rows %}
          <label>{{ r.nombre }} (%)
            <input type="number" name="pct_{{ r.cc|replace(' ', '_') }}" value="{{ '%.4f'|format(r.porcentaje) }}" min="0" max="100" step="0.0001" required>
          </label>
          {% endfor %}
          <p class="help">
            Suma actual:
            <strong style="color:{% if prorrateo.ok %}#1b5e20{% else %}#b71c1c{% endif %}">
              {{ '%.2f'|format(prorrateo.suma) }} %
            </strong>
          </p>
          <div class="form-actions">
            <button class="btn btn-primary" type="submit">Guardar prorrateo</button>
          </div>
        </form>
      </section>
      {% endif %}"""

NEW_PRORRATEO = """      {% if sec == 'prorrateo' and prorrateo %}
      <section class="admin-block">
        <h3>Prorrateo CC</h3>
        <p class="help">
          Porcentajes de imputación de <strong>costos fijos</strong> (sueldos / RRHH y otros gastos prorrateados del fundo).
          Deben sumar <strong>100 %</strong>.
          Superficie en <strong>hectáreas reales</strong> (riego y otros cálculos; no usar % como ha).
          {% if prorrateo.directos %}
          Fuera de este reparto (imputación directa): <strong>{{ prorrateo.directos|join(', ') }}</strong>.
          {% endif %}
          Aplica a movimientos nuevos; no recalcula históricos.
        </p>
        <form method="post" class="form-grid">
          <input type="hidden" name="action" value="prorrateo_guardar">
          <input type="hidden" name="sec" value="prorrateo">
          <div class="table-wrap" style="grid-column:1/-1;">
            <table class="data">
              <thead>
                <tr>
                  <th>Centro de costo</th>
                  <th>Prorrateo %</th>
                  <th>Superficie (ha)</th>
                </tr>
              </thead>
              <tbody>
                {% for r in prorrateo.rows %}
                <tr>
                  <td><strong>{{ r.nombre }}</strong></td>
                  <td>
                    <input type="number" name="pct_{{ r.cc|replace(' ', '_') }}"
                           value="{{ '%.4f'|format(r.porcentaje) }}" min="0" max="100" step="0.0001" required
                           style="max-width:7rem;">
                  </td>
                  <td>
                    <input type="number" name="ha_{{ r.cc|replace(' ', '_') }}"
                           value="{{ '%.2f'|format(r.superficie_ha|default(0)) }}" min="0" step="0.01"
                           style="max-width:7rem;" placeholder="ha">
                  </td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
          <p class="help">
            Suma actual:
            <strong style="color:{% if prorrateo.ok %}#1b5e20{% else %}#b71c1c{% endif %}">
              {{ '%.2f'|format(prorrateo.suma) }} %
            </strong>
          </p>
          <div class="form-actions">
            <button class="btn btn-primary" type="submit">Guardar prorrateo</button>
          </div>
        </form>
      </section>
      {% endif %}"""


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"No existe plantilla fuente: {SOURCE}")
    text = SOURCE.read_text(encoding="utf-8")
    if "{% extends \"_base_app.html\" %}" not in text:
        raise SystemExit("La fuente no extiende _base_app.html (sin sidebar)")
    text = text.replace("{% if tenant.kind == 'lc' %}", "{% if tenant.kind in ['lc', 'espino'] %}")
    if OLD_PRORRATEO not in text:
        raise SystemExit("Bloque prorrateo legacy no encontrado en plantilla fuente")
    text = text.replace(OLD_PRORRATEO, NEW_PRORRATEO, 1)
    TARGET.write_text(text, encoding="utf-8")
    print(f"OK — sidebar restaurado en {TARGET}")


if __name__ == "__main__":
    main()
