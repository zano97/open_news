/* Open News — JS minimo, solo miglioramento progressivo.
   Tutto funziona anche senza JavaScript. */
(function () {
  "use strict";

  // Edizione notturna: memorizzata in localStorage, rispetta prefers-color-scheme di default.
  var KEY = "opennews-tema";
  var root = document.documentElement;

  function applica(tema) {
    root.setAttribute("data-theme", tema || "");
    var bottone = document.querySelector("[data-tema-toggle]");
    if (!bottone) return;
    var notte = temaEffettivo() === "notte";
    bottone.textContent = notte ? "Edizione diurna" : "Edizione notturna";
    bottone.setAttribute(
      "aria-label",
      notte ? "Passa all'edizione diurna" : "Passa all'edizione notturna"
    );
  }

  function temaEffettivo() {
    var scelto = root.getAttribute("data-theme");
    if (scelto === "notte" || scelto === "giorno") return scelto;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "notte" : "giorno";
  }

  try {
    applica(localStorage.getItem(KEY) || "");
  } catch (e) {
    applica("");
  }

  document.addEventListener("click", function (ev) {
    var bottone = ev.target.closest("[data-tema-toggle]");
    if (!bottone) return;
    var nuovo = temaEffettivo() === "notte" ? "giorno" : "notte";
    try {
      localStorage.setItem(KEY, nuovo);
    } catch (e) {
      /* la preferenza semplicemente non persiste */
    }
    applica(nuovo);
  });
})();
