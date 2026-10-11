(function () {
  var conFert = document.getElementById('conFert');
  var fertSection = document.getElementById('fertSection');
  var fertRows = document.getElementById('fertRows');
  var tpl = document.getElementById('fertRowTpl');
  var addBtn = document.getElementById('addFertRow');
  var form = document.getElementById('formRiego');

  function toggleFert() {
    if (!fertSection || !fertRows) return;
    fertSection.classList.toggle('d-none', !conFert || !conFert.checked);
    fertRows.querySelectorAll('select, input').forEach(function (el) {
      el.required = conFert && conFert.checked && el.name === 'fert_producto_id';
      if (!conFert || !conFert.checked) {
        if (el.name === 'fert_cantidad') el.required = false;
      }
    });
  }
  if (conFert) {
    conFert.addEventListener('change', toggleFert);
    toggleFert();
  }
  if (addBtn && tpl && fertRows) {
    addBtn.addEventListener('click', function () {
      fertRows.appendChild(tpl.content.cloneNode(true));
      toggleFert();
    });
  }
  if (fertRows) {
    fertRows.addEventListener('click', function (ev) {
      if (ev.target.classList.contains('js-quitar-fert')) {
        var rows = fertRows.querySelectorAll('.fert-row');
        if (rows.length > 1) ev.target.closest('.fert-row').remove();
      }
    });
  }
  if (form && fertRows) {
    form.addEventListener('submit', function (ev) {
      if (!conFert || !conFert.checked) return;
      var valid = false;
      fertRows.querySelectorAll('.fert-row').forEach(function (row) {
        var pid = row.querySelector('[name=fert_producto_id]');
        var cant = row.querySelector('[name=fert_cantidad]');
        if (pid && pid.value && cant && parseFloat(cant.value) > 0) valid = true;
      });
      if (!valid) {
        ev.preventDefault();
        alert('Indique al menos un fertilizante con cantidad mayor a cero.');
      }
    });
  }

  var cfgEl = document.getElementById('riegoCcConfig');
  var riegoCfg = {};
  if (cfgEl) {
    try { riegoCfg = JSON.parse(cfgEl.textContent || '{}'); } catch (e) { riegoCfg = {}; }
  }

  var huertoEl = document.getElementById('huerto');
  var horasEl = document.getElementById('horas');
  var m3El = document.getElementById('m3');
  var modoBlock = document.getElementById('riegoModoBlock');
  var soloSurcoHint = document.getElementById('riegoSoloSurcoHint');
  var coefHint = document.getElementById('riegoCoefHint');
  var m3Hint = document.getElementById('m3CalcHint');
  var m3AutoTag = document.getElementById('m3AutoTag');
  var modoInputs = document.querySelectorAll('input[name="modo_riego"]');

  function ccSel() {
    return huertoEl ? (huertoEl.value || '').trim().toUpperCase() : '';
  }

  function confSel() {
    return riegoCfg[ccSel()] || null;
  }

  function esSoloSurco() {
    var c = confSel();
    return !!(c && c.solo_surco);
  }

  function modoSel() {
    if (esSoloSurco()) return 'surcos';
    var m = 'horas';
    modoInputs.forEach(function (inp) { if (inp.checked) m = inp.value; });
    return m;
  }

  function esAutoCc() {
    return !!confSel();
  }

  function recalcM3() {
    if (!m3El || !horasEl) return;
    var conf = confSel();
    var horas = parseFloat(horasEl.value) || 0;
    if (!conf) {
      m3El.readOnly = false;
      if (m3AutoTag) m3AutoTag.classList.add('d-none');
      if (m3Hint) m3Hint.classList.add('d-none');
      return;
    }
    m3El.readOnly = true;
    if (m3AutoTag) m3AutoTag.classList.remove('d-none');
    var modo = modoSel();
    var m3 = (modo === 'surcos')
      ? horas * (conf.m3_hr_surco || 40) * conf.ha
      : horas * conf.m3_hr_ha * conf.ha;
    m3El.value = m3 > 0 ? (Math.round(m3 * 100) / 100) : '';
    if (m3Hint) {
      var txt = (modo === 'surcos')
        ? conf.ha + ' ha × ' + (conf.m3_hr_surco || 40) + ' m³/h·ha × ' + horas + ' h'
        : conf.ha + ' ha (prorrateo) × ' + conf.m3_hr_ha + ' m³/h·ha × ' + horas + ' h';
      m3Hint.textContent = 'm³ = ' + txt;
      m3Hint.classList.toggle('d-none', !(horas > 0));
    }
  }

  function refreshUi() {
    var conf = confSel();
    var auto = !!conf;
    var solo = esSoloSurco();
    if (modoBlock) modoBlock.classList.toggle('d-none', !auto || solo);
    if (soloSurcoHint) soloSurcoHint.classList.toggle('d-none', !solo);
    if (coefHint && conf && !solo) {
      coefHint.textContent = (modoSel() === 'surcos')
        ? (conf.m3_hr_surco || 40) + ' m³/h·ha · ' + conf.ha + ' ha (prorrateo)'
        : conf.m3_hr_ha + ' m³/h·ha · ' + conf.ha + ' ha (prorrateo)';
    }
    if (m3Hint) m3Hint.classList.toggle('d-none', !auto);
    recalcM3();
  }

  var hydraEl = document.getElementById('hydraSector');
  var hydraCcHint = document.getElementById('hydraCcHint');
  var hydraMap = {};
  var hydraJson = document.getElementById('hydraSectorsJson');
  if (hydraJson) {
    try { hydraMap = JSON.parse(hydraJson.textContent || '[]'); } catch (e) { hydraMap = []; }
    hydraMap = hydraMap.reduce(function (acc, s) { acc[String(s.relay_id)] = s; return acc; }, {});
  }
  function applyHydraSector() {
    if (!hydraEl || !huertoEl) return;
    var s = hydraMap[hydraEl.value];
    if (!s) {
      huertoEl.value = '';
      if (hydraCcHint) hydraCcHint.textContent = '—';
      refreshUi();
      return;
    }
    huertoEl.value = s.huerto_cc || '';
    if (hydraCcHint) hydraCcHint.textContent = s.huerto_cc || '—';
    if (s.modo_riego === 'surcos') {
      modoInputs.forEach(function (inp) { inp.checked = (inp.value === 'surcos'); });
    } else {
      modoInputs.forEach(function (inp) { inp.checked = (inp.value === 'horas'); });
    }
    refreshUi();
  }
  if (hydraEl) {
    hydraEl.addEventListener('change', applyHydraSector);
    applyHydraSector();
  } else if (huertoEl) {
    huertoEl.addEventListener('change', refreshUi);
  }
  if (horasEl) horasEl.addEventListener('input', recalcM3);
  modoInputs.forEach(function (inp) { inp.addEventListener('change', refreshUi); });
  if (!hydraEl) refreshUi();

  var btn = document.getElementById('btnRegistrarRiego');
  if (!form || !btn) return;

  var enviando = false;
  form.addEventListener('submit', function (ev) {
    if (ev.defaultPrevented) return;
    if (enviando) {
      ev.preventDefault();
      return false;
    }
    if (esAutoCc()) recalcM3();
    enviando = true;
    btn.disabled = true;
    btn.textContent = 'Registrando…';
    setTimeout(function () {
      enviando = false;
      btn.disabled = false;
      btn.textContent = 'Enviar registro';
    }, 70000);
  });
})();
