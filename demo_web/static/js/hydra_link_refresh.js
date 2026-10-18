(function () {
  "use strict";

  var body = document.body;
  if (!body || !body.classList.contains("hydra-link-body")) return;

  var main = document.querySelector(".hydra-link-page");
  var indicator = document.getElementById("hydraPtrIndicator");
  if (!main || !indicator) return;

  var startY = 0;
  var pulling = false;
  var THRESHOLD = 72;

  function refreshUrl() {
    try {
      var u = new URL(window.location.href);
      u.searchParams.set("hydra_sync", "1");
      u.searchParams.delete("hydra_msg");
      u.searchParams.delete("hydra_ok");
      return u.toString();
    } catch (e) {
      return window.location.pathname + window.location.search + "&hydra_sync=1";
    }
  }

  function setPull(px) {
    var p = Math.min(Math.max(px, 0), THRESHOLD + 24);
    indicator.style.transform = "translateY(" + (p - 48) + "px)";
    indicator.textContent =
      p >= THRESHOLD ? "Suelte para actualizar…" : "Deslice hacia abajo para actualizar…";
  }

  main.addEventListener(
    "touchstart",
    function (e) {
      if (window.scrollY > 4) return;
      if (e.touches.length !== 1) return;
      startY = e.touches[0].clientY;
      pulling = true;
    },
    { passive: true }
  );

  main.addEventListener(
    "touchmove",
    function (e) {
      if (!pulling || e.touches.length !== 1) return;
      var dy = e.touches[0].clientY - startY;
      if (dy <= 0) {
        body.classList.remove("hydra-ptr-active");
        setPull(0);
        return;
      }
      if (window.scrollY > 4) {
        pulling = false;
        return;
      }
      body.classList.add("hydra-ptr-active");
      setPull(dy);
      if (dy > 8) e.preventDefault();
    },
    { passive: false }
  );

  function endPull(e) {
    if (!pulling) return;
    pulling = false;
    var dy = 0;
    if (e.changedTouches && e.changedTouches[0]) {
      dy = e.changedTouches[0].clientY - startY;
    }
    body.classList.remove("hydra-ptr-active");
    setPull(0);
    if (dy >= THRESHOLD) {
      indicator.textContent = "Actualizando…";
      window.location.assign(refreshUrl());
    }
  }

  main.addEventListener("touchend", endPull, { passive: true });
  main.addEventListener("touchcancel", endPull, { passive: true });
})();
