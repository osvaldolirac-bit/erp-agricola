(function () {
  var sectorsEl = document.getElementById("hydraSectorsJson");
  var fertOptsEl = document.getElementById("hydraFertOptsJson");
  var ocupadosEl = document.getElementById("hydraOcupadosJson");
  var sectors = [];
  var fertOpts = [];
  var ocupados = [];
  if (sectorsEl) {
    try {
      sectors = JSON.parse(sectorsEl.textContent || "[]");
    } catch (e) {
      sectors = [];
    }
  }
  if (fertOptsEl) {
    try {
      fertOpts = JSON.parse(fertOptsEl.textContent || "[]");
    } catch (e2) {
      fertOpts = [];
    }
  }
  if (ocupadosEl) {
    try {
      ocupados = JSON.parse(ocupadosEl.textContent || "[]") || [];
    } catch (e3) {
      ocupados = [];
    }
  }

  function relayOcupado(id) {
    var n = parseInt(id, 10);
    if (!n) return false;
    for (var i = 0; i < ocupados.length; i++) {
      if (parseInt(ocupados[i], 10) === n) return true;
    }
    return false;
  }

  function sectorByRelay(rid) {
    var n = parseInt(rid, 10);
    for (var i = 0; i < sectors.length; i++) {
      if (parseInt(sectors[i].relay_id, 10) === n) return sectors[i];
    }
    return null;
  }

  function lineasContainer(lineOrContainer) {
    if (lineOrContainer && lineOrContainer.querySelectorAll) {
      return lineOrContainer.id && String(lineOrContainer.id).indexOf("hydraLineas") === 0
        ? lineOrContainer
        : null;
    }
    var el = lineOrContainer && lineOrContainer.closest
      ? lineOrContainer.closest('[id^="hydraLineas"]')
      : null;
    return el;
  }

  function takenRelayIds(container, exceptSelect) {
    var ids = [];
    if (!container) return ids;
    container.querySelectorAll('[name="hw_relay_id"]').forEach(function (sel) {
      if (exceptSelect && sel === exceptSelect) return;
      var v = parseInt(sel.value, 10);
      if (v) ids.push(v);
    });
    return ids;
  }

  function syncSectorOptions(container) {
    if (!container) return;
    container.querySelectorAll('[name="hw_relay_id"]').forEach(function (sel) {
      var taken = takenRelayIds(container, sel);
      sel.querySelectorAll("option").forEach(function (opt) {
        var ov = parseInt(opt.value, 10);
        if (!ov) return;
        opt.disabled = taken.indexOf(ov) >= 0 || relayOcupado(ov);
      });
    });
  }

  function hasDuplicateSectors(container) {
    if (!container) return false;
    var seen = {};
    var dup = false;
    container.querySelectorAll(".hydra-linea").forEach(function (line) {
      var rid = parseInt(line.querySelector('[name="hw_relay_id"]')?.value, 10);
      if (!rid) return;
      if (seen[rid]) dup = true;
      seen[rid] = true;
    });
    return dup;
  }

  function makeFertRow(line, data) {
    var tpl = document.getElementById("hydraFertRowTpl");
    if (!tpl) return null;
    var row = tpl.content.cloneNode(true).querySelector(".hydra-fert-row");
    if (!row) return null;
    var sel = row.querySelector('[name="fert_producto_id"]');
    var cant = row.querySelector('[name="fert_cantidad"]');
    var dosis = row.querySelector('[name="fert_dosis_ha"]');
    if (sel && data && data.producto_id) sel.value = String(data.producto_id);
    if (cant && data && data.cantidad != null) cant.value = data.cantidad;
    if (dosis && data && data.dosis_ha != null && data.dosis_ha !== "") {
      dosis.value = data.dosis_ha;
    }
    line.querySelector(".hydra-fert-rows").appendChild(row);
    return row;
  }

  function toggleLineFert(line) {
    var cb = line.querySelector(".hydra-con-fert");
    var block = line.querySelector(".hydra-fert-block");
    if (!block) return;
    var on = cb && cb.checked;
    block.classList.toggle("d-none", !on);
  }

  function prefillLineFert(line) {
    var selSector = line.querySelector('[name="hw_relay_id"]');
    var rows = line.querySelector(".hydra-fert-rows");
    if (!rows) return;
    rows.innerHTML = "";
    var sec = sectorByRelay(selSector && selSector.value);
    var cb = line.querySelector(".hydra-con-fert");
    var hasDefault = sec && sec.fertilizantes && sec.fertilizantes.length;
    if (cb) cb.checked = !!hasDefault;
    if (hasDefault) {
      sec.fertilizantes.forEach(function (f) {
        makeFertRow(line, f);
      });
    } else {
      makeFertRow(line, null);
    }
    toggleLineFert(line);
  }

  function wireLine(line) {
    var selSector = line.querySelector('[name="hw_relay_id"]');
    if (selSector) {
      selSector.addEventListener("change", function () {
        prefillLineFert(line);
        syncSectorOptions(lineasContainer(line));
      });
    }
    var cb = line.querySelector(".hydra-con-fert");
    if (cb) cb.addEventListener("change", function () {
      toggleLineFert(line);
    });
    line.querySelector(".hydra-add-fert-row")?.addEventListener("click", function () {
      makeFertRow(line, null);
    });
    line.addEventListener("click", function (ev) {
      if (ev.target.classList.contains("hydra-quitar-fert")) {
        var all = line.querySelectorAll(".hydra-fert-row");
        if (all.length > 1) ev.target.closest(".hydra-fert-row").remove();
      }
    });
    if (selSector && selSector.value) prefillLineFert(line);
    else toggleLineFert(line);
  }

  function collectLineas(container) {
    var out = [];
    container.querySelectorAll(".hydra-linea").forEach(function (line) {
      var ridEl = line.querySelector('[name="hw_relay_id"]');
      var minEl = line.querySelector('[name="hw_minutos"]');
      var rid = parseInt(ridEl && ridEl.value, 10);
      var min = parseFloat(minEl && minEl.value) || 0;
      if (!rid || min <= 0) return;
      var con = line.querySelector(".hydra-con-fert");
      var conFert = con && con.checked;
      var fert = [];
      if (conFert) {
        line.querySelectorAll(".hydra-fert-row").forEach(function (row) {
          var pid = parseInt(row.querySelector('[name="fert_producto_id"]')?.value, 10);
          var cant = parseFloat(row.querySelector('[name="fert_cantidad"]')?.value) || 0;
          var dosisRaw = row.querySelector('[name="fert_dosis_ha"]')?.value;
          if (!pid || cant <= 0) return;
          var item = { producto_id: pid, cantidad: cant };
          if (dosisRaw !== undefined && String(dosisRaw).trim() !== "") {
            item.dosis_ha = parseFloat(dosisRaw);
          }
          fert.push(item);
        });
        if (!fert.length) {
          throw new Error("fert");
        }
      }
      out.push({
        relay_id: rid,
        minutos: min,
        con_fertilizacion: !!conFert,
        fertilizantes: fert,
      });
    });
    return out;
  }

  var hydraEnviando = false;
  var hydraEsperaTimer = null;
  var hydraEsperaInicio = 0;

  function bloquearEnvio(on) {
    document
      .querySelectorAll("#formHydraRunNow [type='submit'], #formHydraProgramar [type='submit']")
      .forEach(function (btn) {
        if (on) {
          if (!btn.dataset.prevLabel) btn.dataset.prevLabel = btn.textContent;
          btn.disabled = true;
          btn.textContent = "Enviando…";
        } else {
          btn.disabled = false;
          if (btn.dataset.prevLabel) btn.textContent = btn.dataset.prevLabel;
        }
      });
  }

  function pintarEspera() {
    var reloj = document.getElementById("hydraEsperaReloj");
    var texto = document.getElementById("hydraEsperaTexto");
    var capa = document.getElementById("hydraEspera");
    if (!reloj || !capa) return;
    var seg = Math.max(0, Math.floor((Date.now() - hydraEsperaInicio) / 1000));
    var m = Math.floor(seg / 60);
    var s = seg % 60;
    reloj.textContent = m + ":" + (s < 10 ? "0" : "") + s;
    if (seg >= 45 && texto && !capa.querySelector(".hydra-espera-volver")) {
      texto.textContent =
        "Siga esperando. No vuelva a apretar: revise si el sector ya quedó en riego.";
      var volver = document.createElement("button");
      volver.type = "button";
      volver.className = "btn btn-light hydra-espera-volver";
      volver.textContent = "Volver al formulario";
      volver.addEventListener("click", cerrarEspera);
      capa.appendChild(volver);
    }
  }

  function mostrarEspera() {
    var capa = document.getElementById("hydraEspera");
    if (!capa) {
      capa = document.createElement("div");
      capa.id = "hydraEspera";
      capa.className = "hydra-espera";
      capa.setAttribute("role", "status");
      capa.setAttribute("aria-live", "polite");
      capa.innerHTML =
        '<p class="hydra-espera-titulo">Enviando a Hydrawise</p>' +
        '<p class="hydra-espera-reloj" id="hydraEsperaReloj">0:00</p>' +
        '<p class="hydra-espera-texto" id="hydraEsperaTexto">Espere, no vuelva a apretar.</p>';
      document.body.appendChild(capa);
    }
    capa.hidden = false;
    hydraEsperaInicio = Date.now();
    pintarEspera();
    if (hydraEsperaTimer) clearInterval(hydraEsperaTimer);
    hydraEsperaTimer = setInterval(pintarEspera, 250);
  }

  function cerrarEspera() {
    hydraEnviando = false;
    if (hydraEsperaTimer) {
      clearInterval(hydraEsperaTimer);
      hydraEsperaTimer = null;
    }
    var capa = document.getElementById("hydraEspera");
    if (capa) {
      capa.hidden = true;
      var volver = capa.querySelector(".hydra-espera-volver");
      if (volver) volver.remove();
    }
    var texto = document.getElementById("hydraEsperaTexto");
    if (texto) texto.textContent = "Espere, no vuelva a apretar.";
    bloquearEnvio(false);
  }

  window.addEventListener("pageshow", function (ev) {
    if (ev.persisted) cerrarEspera();
  });

  function bindColaForm(formId, containerId) {
    var form = document.getElementById(formId);
    var container = document.getElementById(containerId);
    if (!form || !container) return;
    container.querySelectorAll(".hydra-linea").forEach(wireLine);
    form.addEventListener("submit", function (ev) {
      if (hydraEnviando) {
        ev.preventDefault();
        return;
      }
      var hidden = form.querySelector('[name="hw_lineas_json"]');
      if (!hidden) return;
      try {
        var data = collectLineas(container);
        if (!data.length) {
          ev.preventDefault();
          alert("Agregue al menos un sector con minutos.");
          return;
        }
        if (hasDuplicateSectors(container)) {
          ev.preventDefault();
          alert("No repita el mismo sector en esta acción.");
          return;
        }
        for (var i = 0; i < data.length; i++) {
          if (relayOcupado(data[i].relay_id)) {
            ev.preventDefault();
            alert("Ese sector está en ejecución. Elija otro.");
            return;
          }
        }
        hidden.value = JSON.stringify(data);
      } catch (err) {
        if (err && err.message === "fert") {
          ev.preventDefault();
          alert("Con fertirriego activo, indique al menos un producto con cantidad mayor a cero.");
        }
        return;
      }
      hydraEnviando = true;
      mostrarEspera();
      // El botón se apaga en el siguiente turno: si se deshabilita dentro del
      // submit, algunos navegadores cancelan el envío que ya iba saliendo.
      setTimeout(function () {
        bloquearEnvio(true);
      }, 0);
    });
  }

  function cloneLineas(containerId, addSel) {
    var container = document.getElementById(containerId);
    if (!container) return;
    var tpl = container.querySelector(".hydra-linea");
    document.querySelector(addSel)?.addEventListener("click", function () {
      var row = tpl.cloneNode(true);
      row.querySelectorAll('input[type="number"]').forEach(function (i) {
        if (i.name === "hw_minutos") i.value = "";
      });
      row.querySelectorAll("select").forEach(function (s) {
        if (s.name === "hw_relay_id") s.selectedIndex = 0;
      });
      var q = row.querySelector(".hydra-quitar");
      if (q) q.classList.remove("d-none");
      container.appendChild(row);
      wireLine(row);
      syncSectorOptions(container);
    });
    container.addEventListener("click", function (ev) {
      if (ev.target.classList.contains("hydra-quitar")) {
        var lines = container.querySelectorAll(".hydra-linea");
        if (lines.length > 1) {
          ev.target.closest(".hydra-linea").remove();
          syncSectorOptions(container);
        }
      }
    });
    syncSectorOptions(container);
  }

  cloneLineas("hydraLineasRun", "#hydraAddLinea");
  cloneLineas("hydraLineasProg", ".hydra-add-prog");
  bindColaForm("formHydraRunNow", "hydraLineasRun");
  bindColaForm("formHydraProgramar", "hydraLineasProg");

  document.querySelectorAll(".hydra-edit-fert-form").forEach(function (form) {
    form.addEventListener("submit", function (ev) {
      var con = form.querySelector('[name="con_fertilizacion"]');
      if (!con || !con.checked) return;
      var ok = false;
      form.querySelectorAll(".hydra-fert-row").forEach(function (row) {
        var pid = row.querySelector('[name="fert_producto_id"]')?.value;
        var cant = parseFloat(row.querySelector('[name="fert_cantidad"]')?.value) || 0;
        if (pid && cant > 0) ok = true;
      });
      if (!ok) {
        ev.preventDefault();
        alert("Indique al menos un fertilizante con cantidad mayor a cero, o desactive fertirriego.");
      }
    });
    var cb = form.querySelector('[name="con_fertilizacion"]');
    var block = form.querySelector(".hydra-fert-block");
    if (cb && block) {
      cb.addEventListener("change", function () {
        block.classList.toggle("d-none", !cb.checked);
      });
    }
    form.querySelector(".hydra-add-fert-row")?.addEventListener("click", function () {
      var wrap = form.querySelector(".hydra-fert-rows");
      var tpl = document.getElementById("hydraFertRowTpl");
      if (wrap && tpl) wrap.appendChild(tpl.content.cloneNode(true));
    });
  });
})();
