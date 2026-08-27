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
    // Etichette localizzate fornite dal server nei data-attribute.
    bottone.textContent = notte
      ? bottone.getAttribute("data-label-giorno") || "Edizione diurna"
      : bottone.getAttribute("data-label-notte") || "Edizione notturna";
    bottone.setAttribute(
      "aria-label",
      (notte
        ? bottone.getAttribute("data-aria-giorno")
        : bottone.getAttribute("data-aria-notte")) || bottone.textContent
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

  // Edizione lampo: navigazione con i tasti freccia (miglioramento progressivo;
  // senza JS il reel resta una lista verticale scorrevole).
  var reel = document.getElementById("reel");
  if (reel) {
    var schede = Array.prototype.slice.call(reel.querySelectorAll(".reel-scheda"));
    function corrente() {
      var top = reel.scrollTop;
      var best = 0;
      schede.forEach(function (s, i) {
        if (Math.abs(s.offsetTop - top) < Math.abs(schede[best].offsetTop - top)) best = i;
      });
      return best;
    }
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
      if (/^(input|textarea|select)$/i.test(document.activeElement.tagName)) return;
      ev.preventDefault();
      var i = corrente() + (ev.key === "ArrowDown" ? 1 : -1);
      if (i >= 0 && i < schede.length) {
        schede[i].scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
})();
