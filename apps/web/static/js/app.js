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
          var esito = testo.textContent.trim();
          // "⚠" è la sentinella del server per un esito non valido.
          if (esito.length < 40 || esito.indexOf("\u26a0") !== -1) throw new Error("");
          btn.remove();
          if (nota) nota.hidden = false;
        })
        .catch(function (err) {
          btn.disabled = false;
          btn.textContent = etichetta; // il motivo sta nel riquadro, non sul bottone
          testo.hidden = false;
          testo.classList.add("riassunto-errore");
          if (err && err.message) {
            testo.textContent = err.message;
          } else if (!testo.textContent.trim()) {
            testo.textContent = btn.getAttribute("data-errore") || "";
          }
        });
    });
  }

  // Barra di aggiornamento: compare quando un ciclo lavora (automatico o
  // manuale). Se l'aggiornamento l'ha chiesto il lettore, a fine giro la
  // pagina si ricarica da sola: "quando ha finito, le mostra".
  var barra = document.querySelector("[data-aggiorna-barra]");
  if (barra && window.fetch) {
    var FLAG = "opennews-aggiorna-richiesto";
    var form = document.querySelector("[data-aggiorna-form]");
    if (form) {
      form.addEventListener("submit", function () {
        try { sessionStorage.setItem(FLAG, "1"); } catch (e) { /* pazienza */ }
      });
    }
    var eraInCorso = !barra.hidden;
    var eraManuale = false;
    var storyIniziale = null;
    var bottoneAgg = document.querySelector(".aggiorna-bottone");
    var etichettaAgg = bottoneAgg ? bottoneAgg.textContent : "";
    function applicaStato(stato) {
      barra.hidden = !stato.in_corso;
      if (stato.in_corso) {
        if (typeof stato.percento === "number") {
          barra.classList.remove("indeterminata");
          barra.style.setProperty("--avanzamento", stato.percento + "%");
        } else {
          barra.classList.add("indeterminata");
          barra.style.setProperty("--avanzamento", "100%");
        }
      }
      // Il BOTTONE segue solo il giro chiesto dal lettore; la barra
      // racconta anche i cicli automatici.
      if (bottoneAgg) {
        if (stato.giro_manuale) {
          bottoneAgg.disabled = true;
          var dettaglio = "";
          if (typeof stato.percento === "number") dettaglio += " " + stato.percento + "%";
          if (stato.fase) dettaglio += " · " + stato.fase;
          bottoneAgg.textContent =
            (bottoneAgg.getAttribute("data-attendi") || "…") + dettaglio;
        } else {
          bottoneAgg.disabled = false;
          bottoneAgg.textContent = bottoneAgg.getAttribute("data-riposo") || etichettaAgg;
        }
      }
      var ultimo = document.querySelector("[data-ultimo]");
      if (ultimo && stato.ultimo) ultimo.textContent = stato.ultimo;
      // Notizie nuove a pagina aperta: quando la story più recente cambia
      // rispetto al caricamento e il giro è finito, compare l'avviso.
      if (stato.story_recente) {
        if (storyIniziale === null) {
          storyIniziale = stato.story_recente;
        } else if (stato.story_recente !== storyIniziale && !stato.in_corso) {
          var avviso = document.querySelector("[data-notizie-nuove]");
          if (avviso) avviso.hidden = false;
        }
      }
      // La ricarica segue SOLO il giro chiesto dal lettore: i cicli
      // automatici che si accodano non la trattengono all'infinito.
      var richiesto = false;
      try { richiesto = sessionStorage.getItem(FLAG) === "1"; } catch (e) { /* niente */ }
      if (eraManuale && !stato.giro_manuale && richiesto) {
        try { sessionStorage.removeItem(FLAG); } catch (e) { /* niente */ }
        location.reload();
      }
      eraManuale = !!stato.giro_manuale;
      eraInCorso = stato.in_corso;
    }
    setInterval(function () {
      if (document.hidden) return;
      fetch("/api/aggiornamento").then(function (r) { return r.json(); })
        .then(applicaStato)
        .catch(function () { /* server in riavvio: si riprova al giro dopo */ });
    }, 3000);
  }

  // Profilo pubblico di una testata in raccolta: una sonda leggera chiede
  // ogni 3 secondi se è pronto e ricarica APPENA lo è — niente attese
  // cieche. Se la raccolta fallisce (sito irraggiungibile), la sonda si
  // ferma e la barra di attesa si spegne: nessun loop infinito.
  var attesaOsint = document.querySelector("[data-osint-in-corso]");
  if (attesaOsint && window.fetch) {
    var slugOsint = attesaOsint.getAttribute("data-slug") || "";
    var barraOsint = document.querySelector(".barra-attesa");
    var tentativiOsint = 0;
    var sondaOsint = setInterval(function () {
      tentativiOsint += 1;
      if (tentativiOsint > 30) {  // ~90 secondi, poi basta
        clearInterval(sondaOsint);
        if (barraOsint) barraOsint.hidden = true;
        return;
      }
      fetch("/api/osint/" + encodeURIComponent(slugOsint))
        .then(function (r) { return r.json(); })
        .then(function (stato) {
          if (stato.pronto) {
            clearInterval(sondaOsint);
            location.reload();
          } else if (!stato.in_corso && tentativiOsint > 2) {
            clearInterval(sondaOsint);
            if (barraOsint) barraOsint.hidden = true;
          }
        })
        .catch(function () { /* server in riavvio: al prossimo giro */ });
    }, 3000);
  }

  // L'avviso «notizie nuove»: un tocco ricarica; al ritorno sulla
  // finestra (se l'avviso è già comparso) la pagina si rinnova da sola.
  document.addEventListener("click", function (ev) {
    if (ev.target.closest("[data-notizie-nuove]")) location.reload();
  });
  document.addEventListener("visibilitychange", function () {
    var avviso = document.querySelector("[data-notizie-nuove]");
    if (!document.hidden && avviso && !avviso.hidden) location.reload();
  });

  // I link alle testate escono dall'app: si aprono nel browser (nuova
  // scheda/finestra), mai DENTRO la finestra del giornale, che non ha
  // una barra degli indirizzi per tornare indietro.
  document.addEventListener("click", function (ev) {
    var a = ev.target.closest("a[href]");
    if (!a || !a.host) return;
    if (a.host !== window.location.host) {
      a.target = "_blank";
      a.rel = "noopener";
    }
  });

  // Nomi dei paesi nella lingua dell'interfaccia: li sa già il browser
  // (Intl.DisplayNames), niente elenchi da mantenere in cinque lingue.
  var nomiPaesi = null;
  try {
    nomiPaesi = new Intl.DisplayNames([document.documentElement.lang || "it"], { type: "region" });
  } catch (e) { /* browser datato: restano le sigle */ }
  if (nomiPaesi) {
    Array.prototype.forEach.call(document.querySelectorAll(".chip-nome[data-paese]"), function (el) {
      var codice = (el.getAttribute("data-paese") || "").toUpperCase();
      try {
        var nome = nomiPaesi.of(codice);
        if (nome && nome !== codice) el.textContent = nome;
      } catch (e) { /* codice non ISO: resta la sigla */ }
    });
  }

  // Mappa del mondo (/paesi): clic su un paese coperto = filtro.
  var mappa = document.querySelector("[data-mappa-mondo]");
  var datiMappa = document.getElementById("dati-mappa");
  if (mappa && datiMappa) {
    var conteggi = {};
    try { conteggi = JSON.parse(datiMappa.textContent) || {}; } catch (e) { /* vuota */ }
    Array.prototype.forEach.call(mappa.querySelectorAll("svg path[id]"), function (path) {
      var codice = path.id;
      if (!Object.prototype.hasOwnProperty.call(conteggi, codice)) return;
      path.classList.add("paese-cliccabile");
      var nome = codice.toUpperCase();
      if (nomiPaesi) { try { nome = nomiPaesi.of(codice.toUpperCase()) || nome; } catch (e) { /* sigla */ } }
      var titolo = document.createElementNS("http://www.w3.org/2000/svg", "title");
      titolo.textContent = nome + " · " + conteggi[codice];
      path.appendChild(titolo);
      path.addEventListener("click", function () {
        window.location.href = "/?paese=" + codice;
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
