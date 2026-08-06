(function () {
  var btn = document.querySelector(".nav-toggle");
  var nav = document.querySelector(".top-nav");
  if (btn && nav) {
    btn.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      btn.setAttribute("aria-expanded", open ? "true" : "false");
    });
    nav.querySelectorAll("a").forEach(function (a) {
      a.addEventListener("click", function () {
        nav.classList.remove("open");
        btn.setAttribute("aria-expanded", "false");
      });
    });
  }

  var zona = document.querySelector(".zona-clientes");
  var zonaBtn = document.querySelector(".zona-clientes-toggle");
  var zonaMenu = document.querySelector(".zona-clientes-menu");
  if (!zona || !zonaBtn || !zonaMenu) return;

  function closeZona() {
    zona.classList.remove("open");
    zonaBtn.setAttribute("aria-expanded", "false");
    zonaMenu.hidden = true;
  }

  function openZona() {
    zona.classList.add("open");
    zonaBtn.setAttribute("aria-expanded", "true");
    zonaMenu.hidden = false;
  }

  zonaBtn.addEventListener("click", function (e) {
    e.stopPropagation();
    if (zona.classList.contains("open")) closeZona();
    else openZona();
  });

  document.addEventListener("click", function (e) {
    if (!zona.contains(e.target)) closeZona();
  });

  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") closeZona();
  });
})();
