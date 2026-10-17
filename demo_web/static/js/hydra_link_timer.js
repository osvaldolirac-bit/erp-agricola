(function () {
  "use strict";

  function fmt(sec) {
    var s = Math.max(0, Math.floor(sec));
    var m = Math.floor(s / 60);
    var r = s % 60;
    if (m >= 60) {
      var h = Math.floor(m / 60);
      m = m % 60;
      return h + ":" + String(m).padStart(2, "0") + ":" + String(r).padStart(2, "0");
    }
    return m + ":" + String(r).padStart(2, "0");
  }

  var nodes = document.querySelectorAll(".hydra-zone-timer[data-remaining-sec]");
  if (!nodes.length) return;

  var timers = [];
  nodes.forEach(function (el) {
    var sec = parseInt(el.getAttribute("data-remaining-sec") || "0", 10);
    if (isNaN(sec) || sec < 0) sec = 0;
    var val = el.querySelector(".hydra-zone-timer-value");
    timers.push({ el: el, val: val, sec: sec });
  });

  function tick() {
    var any = false;
    timers.forEach(function (t) {
      if (t.sec <= 0) {
        if (t.val) t.val.textContent = "0:00";
        t.el.classList.add("hydra-zone-timer--done");
        return;
      }
      any = true;
      if (t.val) t.val.textContent = fmt(t.sec);
      t.sec -= 1;
    });
    if (any) {
      window.setTimeout(tick, 1000);
    }
  }

  tick();
})();
