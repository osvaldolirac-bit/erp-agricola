(function () {
  "use strict";

  var jsonEl = document.getElementById("hydraEjecucionJson");
  var backdrop = document.getElementById("hydraRunDetailBackdrop");
  if (!jsonEl || !backdrop) return;

  var byRelay = {};
  try {
    byRelay = JSON.parse(jsonEl.textContent || "{}") || {};
  } catch (e) {
    byRelay = {};
  }

  function qs(id) {
    return document.getElementById(id);
  }

  function openDetail(relayId) {
    var d = byRelay[String(relayId)] || byRelay[relayId];
    if (!d) return;
    qs("hydraRunDetailTitle").textContent = d.label || "Riego en curso";
    qs("hydraRunDetailCc").textContent = d.huerto_cc || "";
    qs("hydraRunDetailModo").textContent = d.tipo_label || "—";
    qs("hydraRunDetailCola").textContent = d.cola_id
      ? "#" + d.cola_id + (d.inicio_programa_fmt ? " · prog. " + d.inicio_programa_fmt : "")
      : "—";
    qs("hydraRunDetailInicio").textContent = d.run_inicio_fmt || "—";
    qs("hydraRunDetailFin").textContent = d.fin_estimado_fmt || "—";
    qs("hydraRunDetailDuracion").textContent = d.minutos_fmt || "—";
    qs("hydraRunDetailRestante").textContent = d.remaining_fmt || "—";
    var reg = (d.creado_por || "").trim();
    qs("hydraRunDetailRegadorRow").style.display = reg ? "" : "none";
    qs("hydraRunDetailRegador").textContent = reg || "—";
    var list = qs("hydraRunDetailFertList");
    var sinFert = qs("hydraRunDetailSinFert");
    list.innerHTML = "";
    var fert = d.fertilizantes || [];
    if (d.tiene_fertirriego && fert.length) {
      sinFert.classList.add("d-none");
      fert.forEach(function (f) {
        var li = document.createElement("li");
        var txt = f.nombre + " — " + (f.cantidad_fmt || "");
        if (f.dosis_fmt) txt += " · " + f.dosis_fmt;
        li.textContent = txt;
        list.appendChild(li);
      });
    } else {
      sinFert.classList.remove("d-none");
    }
    backdrop.hidden = false;
    backdrop.setAttribute("aria-hidden", "false");
    document.body.classList.add("hydra-run-detail-open");
  }

  function closeDetail() {
    backdrop.hidden = true;
    backdrop.setAttribute("aria-hidden", "true");
    document.body.classList.remove("hydra-run-detail-open");
  }

  document.querySelectorAll(".hydra-zone-card--tappable").forEach(function (el) {
    el.addEventListener("click", function () {
      var rid = el.getAttribute("data-relay");
      if (rid) openDetail(rid);
    });
  });

  qs("hydraRunDetailClose").addEventListener("click", closeDetail);
  backdrop.addEventListener("click", function (e) {
    if (e.target === backdrop) closeDetail();
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && !backdrop.hidden) closeDetail();
  });
})();
