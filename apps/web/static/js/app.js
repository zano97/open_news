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

  // "Il fatto in breve" su richiesta: streaming del riassunto nella pagina.
  var bottoneRiassunto = document.querySelector("[data-riassunto-btn]");
  if (bottoneRiassunto && window.fetch) {
    bottoneRiassunto.addEventListener("click", function () {
      var btn = bottoneRiassunto;
      var testo = document.querySelector("[data-riassunto-testo]");
      var nota = document.querySelector("[data-riassunto-nota]");
      var etichetta = btn.textContent;
      btn.disabled = true;
      btn.textContent = btn.getAttribute("data-attendi") || "…";
      testo.hidden = false;
      testo.textContent = "";
      fetch(btn.getAttribute("data-url"), { method: "POST" })
        .then(function (resp) {
          if (!resp.ok) {
            // Il server spiega il motivo (Ollama spento, modello mancante…):
            // mostriamolo al lettore invece di fallire in silenzio.
            return resp.text().then(function (corpo) {
              var msg = "";
              try { msg = JSON.parse(corpo).detail || ""; } catch (e) { /* testo */ }
              throw new Error(msg || corpo || "HTTP " + resp.status);
            });
          }
          if (!resp.body) throw new Error("HTTP " + resp.status);
          var reader = resp.body.getReader();
          var decoder = new TextDecoder();
          function leggi() {
            return reader.read().then(function (blocco) {
              if (blocco.done) return;
              testo.textContent += decoder.decode(blocco.value, { stream: true });
              return leggi();
            });
          }
          return leggi();
        })
        .then(function () {
          if (testo.textContent.trim().length < 40) throw new Error("");
          btn.remove();
          if (nota) nota.hidden = false;
        })
        .catch(function (err) {
          btn.disabled = false;
          btn.textContent = btn.getAttribute("data-errore") || etichetta;
          if (err && err.message) {
            testo.hidden = false;
            testo.textContent = err.message;
            testo.classList.add("riassunto-errore");
          }
        });
    });
  }

  // Edizione lampo: navigazione con i tasti freccia (miglioramento progressivo;
  // senza JS il reel resta una lista verticale scorrevole).
  var reel = document.getElementById("reel");
  if (reel) {
    var schede = Array.prototype.slice.call(reel.querySelectorAll(".reel-scheda"));
    function corrente() {
      var best = 0;
      var distanza = Infinity;
      schede.forEach(function (s, i) {
        var d = Math.abs(s.getBoundingClientRect().top);
        if (d < distanza) { distanza = d; best = i; }
      });
      return best;
    }
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "ArrowDown" && ev.key !== "ArrowUp") return;
      if (/^(input|textarea|select)$/i.test(document.activeElement.tagName)) return;
      var i = corrente() + (ev.key === "ArrowDown" ? 1 : -1);
      if (i >= 0 && i < schede.length) {
        ev.preventDefault();
        schede[i].scrollIntoView({ behavior: "smooth", block: "start" });
      }
    });
  }
})();
