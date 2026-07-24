/* Demo ERP — utilidades JS compartidas */
(function () {
  var DATE_HDR = /fecha|vencim|registro|viable|periodo|desde|hasta/i;

  function parseDateSortKey(text) {
    var s = String(text || '').trim();
    if (!s || s === '—' || s === '-') return null;
    var m = s.match(/^(\d{2})-(\d{2})-(\d{4})(?:\s|$)/);
    if (m) {
      return parseInt(m[3], 10) * 10000 + parseInt(m[2], 10) * 100 + parseInt(m[1], 10);
    }
    m = s.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T]|$)/);
    if (m) {
      return parseInt(m[1], 10) * 10000 + parseInt(m[2], 10) * 100 + parseInt(m[3], 10);
    }
    return null;
  }

  function dateColumnIndexes(table) {
    var idx = [];
    table.querySelectorAll('thead th').forEach(function (th, i) {
      if (DATE_HDR.test(th.textContent || '')) idx.push(i);
    });
    return idx;
  }

  function applyDateSortKeys(table) {
    var cols = dateColumnIndexes(table);
    if (!cols.length) return;
    table.querySelectorAll('tbody tr').forEach(function (tr) {
      var cells = tr.querySelectorAll('td');
      cols.forEach(function (ci) {
        var td = cells[ci];
        if (!td || td.getAttribute('data-order')) return;
        var key = parseDateSortKey(td.textContent);
        if (key != null) td.setAttribute('data-order', String(key));
      });
    });
  }

  function initDataTable(table, options) {
    if (!window.jQuery || !$.fn.DataTable || $.fn.DataTable.isDataTable(table)) return;
    applyDateSortKeys(table);
    var opts = Object.assign({
      autoWidth: false,
      initComplete: function () {
        this.api().columns.adjust();
      }
    }, options || {});
    var dt = $(table).DataTable(opts);
    dt.on('draw.dt', function () {
      dt.columns.adjust();
    });
    if (!window._erpDtResizeBound) {
      window._erpDtResizeBound = true;
      window.addEventListener('resize', function () {
        document.querySelectorAll('.demo-datatable, .demo-datatable-bitacora').forEach(function (el) {
          if ($.fn.DataTable.isDataTable(el)) {
            $(el).DataTable().columns.adjust();
          }
        });
      });
    }
  }

  $(function () {
    document.querySelectorAll('.demo-datatable-bitacora').forEach(function (table) {
      initDataTable(table, {
        pageLength: 50,
        order: [],
        language: { url: 'https://cdn.datatables.net/plug-ins/1.13.8/i18n/es-ES.json' }
      });
    });
    document.querySelectorAll('.demo-datatable').forEach(function (table) {
      initDataTable(table, {
        pageLength: 25,
        order: [],
        language: { url: 'https://cdn.datatables.net/plug-ins/1.13.8/i18n/es-ES.json' }
      });
    });

    var menu = document.getElementById('demoMenu');
    if (menu) {
      var desktopMq = window.matchMedia('(min-width: 992px)');

      function pinDesktopSidebar() {
        if (desktopMq.matches) {
          menu.classList.add('demo-sidebar-desktop');
        } else {
          menu.classList.remove('demo-sidebar-desktop');
          menu.classList.remove('show');
        }
      }

      pinDesktopSidebar();
      desktopMq.addEventListener('change', pinDesktopSidebar);

      menu.querySelectorAll('.demo-menu a').forEach(function (link) {
        link.addEventListener('click', function () {
          if (!desktopMq.matches && window.bootstrap && bootstrap.Offcanvas) {
            var inst = bootstrap.Offcanvas.getInstance(menu);
            if (inst) inst.hide();
          }
        });
      });
    }

    initPdfShareButtons();
  });

  function esIosWeb() {
    /* iPhone/iPad: Safari, Chrome (CriOS), Firefox (FxiOS), Edge (EdgiOS) — todos WebKit */
    var ua = (navigator.userAgent || '').toLowerCase();
    return /iphone|ipad|ipod|crios|fxios|edgios/.test(ua) ||
      (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  }

  function parseFilenameFromDisposition(header) {
    if (!header) return null;
    var m = /filename\*=UTF-8''([^;]+)|filename="([^"]+)"|filename=([^;]+)/i.exec(header);
    if (!m) return null;
    var raw = (m[1] || m[2] || m[3] || '').trim();
    try {
      return decodeURIComponent(raw);
    } catch (e) {
      return raw;
    }
  }

  function iosViewLabel(label) {
    var lbl = String(label || 'PDF').replace(/📥/g, '').replace(/📤/g, '').replace(/📄/g, '').trim();
    lbl = lbl.replace(/^DESCARGAR\s+/i, '').replace(/^PDF\s*/i, '').trim() || 'PDF';
    return '📄 Ver PDF — ' + lbl;
  }

  function toPdfViewUrl(downloadHref) {
    try {
      var u = new URL(downloadHref, window.location.href);
      var m = u.pathname.match(/\/pdf\/([^/]+)$/);
      if (!m) return downloadHref;
      u.pathname = u.pathname.replace(/\/pdf\/[^/]+$/, '/pdf/view/' + m[1]);
      u.searchParams.set('back', window.location.href);
      u.hash = '';
      return u.pathname + u.search;
    } catch (e) {
      return downloadHref;
    }
  }

  function toPdfInlineUrl(downloadHref) {
    try {
      var u = new URL(downloadHref, window.location.href);
      u.searchParams.set('inline', '1');
      return u.pathname + u.search;
    } catch (e) {
      return downloadHref;
    }
  }

  async function abrirPdfMovilIos(btn) {
    var url = toPdfInlineUrl(btn.getAttribute('href'));
    var originalText = btn.textContent;
    btn.dataset.pdfBusy = '1';
    btn.setAttribute('aria-busy', 'true');
    btn.textContent = 'Cargando PDF…';

    try {
      var resp = await fetch(url, { credentials: 'same-origin' });
      if (!resp.ok) throw new Error('PDF no disponible o expirado.');
      var blob = await resp.blob();
      var filename = btn.getAttribute('data-pdf-filename') ||
        parseFilenameFromDisposition(resp.headers.get('Content-Disposition')) ||
        'documento.pdf';
      var blobUrl = URL.createObjectURL(blob);
      /* Visor nativo del navegador (Chrome/Safari en iPhone) — PDF completo, no iframe */
      window.location.assign(blobUrl);
    } catch (err) {
      window.location.href = url;
    } finally {
      delete btn.dataset.pdfBusy;
      btn.removeAttribute('aria-busy');
      btn.textContent = originalText;
    }
  }

  async function handlePdfShareClick(e) {
    var btn = e.currentTarget;
    var url = btn.getAttribute('data-pdf-url') || btn.getAttribute('href');
    if (!url || btn.dataset.pdfBusy === '1') return;
    e.preventDefault();

    var originalText = btn.textContent;
    btn.dataset.pdfBusy = '1';
    btn.setAttribute('aria-busy', 'true');
    btn.textContent = 'Preparando PDF…';

    try {
      var resp = await fetch(url, { credentials: 'same-origin' });
      if (!resp.ok) throw new Error('PDF no disponible o expirado.');
      var blob = await resp.blob();
      var filename = btn.getAttribute('data-pdf-filename') ||
        parseFilenameFromDisposition(resp.headers.get('Content-Disposition')) ||
        'documento.pdf';
      var file = new File([blob], filename, { type: 'application/pdf' });

      if (navigator.canShare && navigator.canShare({ files: [file] })) {
        await navigator.share({ files: [file], title: filename });
        return;
      }

      var blobUrl = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = blobUrl;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(function () { URL.revokeObjectURL(blobUrl); }, 1500);
    } catch (err) {
      if (err && err.name === 'AbortError') return;
      window.alert((err && err.message) ? err.message : 'No se pudo compartir el PDF.');
    } finally {
      delete btn.dataset.pdfBusy;
      btn.removeAttribute('aria-busy');
      btn.textContent = originalText;
    }
  }

  function initPdfShareButtons() {
    document.querySelectorAll('.erp-pdf-share-btn[data-pdf-url]').forEach(function (btn) {
      if (btn.dataset.pdfShareBound === '1') return;
      btn.dataset.pdfShareBound = '1';
      btn.addEventListener('click', handlePdfShareClick);
    });

    if (!esIosWeb()) return;
    document.body.classList.add('erp-ios');

    document.querySelectorAll('a.erp-pdf-btn[href]').forEach(function (btn) {
      if (btn.dataset.pdfIosBound === '1') return;
      btn.dataset.pdfIosBound = '1';
      var label = (btn.getAttribute('data-pdf-label') || btn.textContent || 'PDF').trim();
      var rows = btn.getAttribute('data-pdf-rows');
      btn.setAttribute('data-pdf-label', label);
      btn.textContent = iosViewLabel(label);
      btn.removeAttribute('download');
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        abrirPdfMovilIos(btn);
      });
    });
  }

  function limpiarRut(rut) {
    return String(rut || '').replace(/[^0-9kK]/g, '').toUpperCase();
  }

  function digitoVerificadorRut(cuerpo) {
    var factores = [2, 3, 4, 5, 6, 7];
    var total = 0;
    var i = 0;
    for (var j = cuerpo.length - 1; j >= 0; j--) {
      total += parseInt(cuerpo.charAt(j), 10) * factores[i % 6];
      i += 1;
    }
    var resto = 11 - (total % 11);
    if (resto === 11) return '0';
    if (resto === 10) return 'K';
    return String(resto);
  }

  function rutEsValido(rut) {
    var limpio = limpiarRut(rut);
    if (limpio.length < 2) return false;
    var cuerpo = limpio.slice(0, -1);
    var dv = limpio.slice(-1);
    if (!/^\d+$/.test(cuerpo) || parseInt(cuerpo, 10) === 0) return false;
    return digitoVerificadorRut(cuerpo) === dv;
  }

  function formatearRut(rut) {
    var limpio = limpiarRut(rut);
    if (!limpio) return '';
    var cuerpo = limpio.slice(0, -1);
    var dv = limpio.slice(-1);
    var partes = [];
    while (cuerpo.length > 3) {
      partes.unshift(cuerpo.slice(-3));
      cuerpo = cuerpo.slice(0, -3);
    }
    if (cuerpo) partes.unshift(cuerpo);
    return partes.join('.') + '-' + dv;
  }

  function rutFeedbackEl(input) {
    var wrap = input.parentElement;
    if (!wrap) return null;
    var msg = wrap.querySelector('.js-rut-msg');
    if (!msg) {
      msg = document.createElement('div');
      msg.className = 'invalid-feedback js-rut-msg';
      wrap.appendChild(msg);
    }
    return msg;
  }

  function setRutEstado(input, ok, mensaje) {
    var msg = rutFeedbackEl(input);
    if (ok) {
      input.classList.remove('is-invalid');
      input.setCustomValidity('');
      if (msg) {
        msg.textContent = '';
        msg.style.display = 'none';
      }
      return;
    }
    input.classList.add('is-invalid');
    input.setCustomValidity(mensaje || 'RUT incorrecto');
    if (msg) {
      msg.textContent = mensaje || 'RUT incorrecto';
      msg.style.display = 'block';
    }
  }

  function validarInputRut(input, opts) {
    opts = opts || {};
    var required = input.hasAttribute('required') ||
      input.getAttribute('data-rut-required') === '1' ||
      (opts.required === true);
    var raw = String(input.value || '').trim();
    if (!raw) {
      if (required) {
        setRutEstado(input, false, 'Ingrese un RUT.');
        return false;
      }
      setRutEstado(input, true, '');
      return true;
    }
    if (!rutEsValido(raw)) {
      setRutEstado(input, false, 'RUT incorrecto. Verifique el número y el dígito verificador.');
      return false;
    }
    if (opts.format !== false) {
      input.value = formatearRut(raw);
    }
    setRutEstado(input, true, '');
    return true;
  }

  function initRutInputs() {
    document.querySelectorAll('input.js-rut').forEach(function (input) {
      if (input.dataset.rutBound === '1') return;
      input.dataset.rutBound = '1';
      input.setAttribute('autocomplete', 'off');
      input.addEventListener('blur', function () {
        validarInputRut(input, { format: true });
      });
      input.addEventListener('input', function () {
        if (input.classList.contains('is-invalid')) {
          validarInputRut(input, { format: false });
        }
      });
      var form = input.form;
      if (form && form.dataset.rutSubmitBound !== '1') {
        form.dataset.rutSubmitBound = '1';
        form.addEventListener('submit', function (e) {
          var ok = true;
          form.querySelectorAll('input.js-rut').forEach(function (rutInput) {
            if (!validarInputRut(rutInput, { format: true })) ok = false;
          });
          if (!ok) {
            e.preventDefault();
            e.stopPropagation();
            var first = form.querySelector('input.js-rut.is-invalid');
            if (first) first.focus();
          }
        });
      }
    });
  }

  $(function () {
    initRutInputs();
  });

  window.demoInitDataTable = initDataTable;
  window.demoValidarRut = validarInputRut;
  window.demoRutEsValido = rutEsValido;
  window.demoFormatearRut = formatearRut;
})();
