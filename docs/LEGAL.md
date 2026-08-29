# Note legali

Questo documento descrive le scelte del progetto per rispettare i diritti
degli editori e le norme applicabili. Non è un parere legale; chi eroga
un'istanza pubblica di Open News è responsabile della propria conformità.

## Che cosa mostriamo dei contenuti delle testate

- **Titolo**, **snippet breve** (massimo ~200 caratteri, troncato a parola),
  **immagine di anteprima** solo se fornita dall'editore nel feed, e **link
  alla fonte**. Questo rientra nella prassi della citazione con rinvio alla
  fonte (art. 70 l. 633/1941 per l'Italia; per gli estratti brevi si tengono
  presenti anche l'art. 15 direttiva (UE) 2019/790 e l'art. 43-bis
  l. 633/1941, che fanno salvi gli "estratti molto brevi" e i collegamenti).
- Il **testo integrale** può essere scaricato per l'analisi locale
  (conteggi aggregati: lessico, attori, tono) ma **non è mai mostrato, mai
  esposto dalle API, mai ridistribuito**. La colonna che lo contiene è
  interna e nessun endpoint la serializza.
- Non aggiriamo paywall; non ripubblichiamo lanci di agenzia.
- Il **riassunto neutro** ("il fatto in breve") mostrato nella pagina di una
  story non è testo delle testate: è generato in locale da un modello aperto
  che legge titoli, estratti e il testo integrale raccolto per uso interno
  (mai più di un frammento per articolo) e RISCRIVE i fatti in parole
  proprie — il prompt vieta esplicitamente frasi copiate, e il testo
  integrale continua a non essere mai mostrato né esposto. Il riassunto è
  sempre marcato come automatico e rimanda agli articoli originali, che
  restano l'unica versione che fa fede. I fatti in sé non sono oggetto di
  diritto d'autore; la forma espressiva delle testate non viene riprodotta.

## Come raccogliamo

- **robots.txt rispettato per il crawling**: pagine web (homepage per
  l'autodiscovery, pagine articolo, testo integrale), con cache; in assenza
  del file l'accesso è consentito come da prassi. Il fetch dei **feed
  RSS/Atom** non passa dal filtro robots: un feed è pubblicato apposta per
  essere letto dagli aggregatori per conto dei lettori iscritti, e i
  lettori di feed non applicano robots al feed stesso (Google Feedfetcher
  documenta esplicitamente questo comportamento e il perché). Restano
  sempre attivi rate limit, cache condizionale e User-Agent identificativo.
  Vedi ADR-0025.
- **User-Agent identificativo** (`OpenNewsBot`, con link al repository).
- **Rate limit per dominio**: massimo una richiesta ogni 2 secondi per
  ciascun sito (5 secondi per GDELT, come richiesto dal servizio).
- **Cache HTTP condizionale** (ETag / Last-Modified): se un feed non è
  cambiato non lo riscarichiamo.
- **Allowlist di rete**: il codice può contattare solo i domini delle fonti
  nel catalogo e i servizi gratuiti documentati (GDELT, Wikidata, registri
  pubblici). Ogni altra destinazione viene rifiutata dal client HTTP e il
  vincolo è coperto da test.

## Termini d'uso per fonte

Ogni fonte del catalogo (`data/sources.yaml`) ha un campo `terms_note` con
le restrizioni note dei suoi termini d'uso. Quando i termini vietano l'uso
in un aggregatore, la fonte è **disabilitata di default** con la
motivazione visibile nella sua scheda: è il caso di **ANSA**, i cui termini
per i feed RSS consentono solo uso personale non commerciale e vietano la
ripubblicazione dei titoli su siti web. La fonte resta nel catalogo per
trasparenza e può essere abilitata solo previo accordo con l'editore.

Reuters e Associated Press non offrono feed RSS pubblici: la loro copertura
è rilevata tramite i metadati di **GDELT** (titolo e link; con citazione del
GDELT Project come richiesto), senza ripubblicare alcun contenuto.

## Tracce pubbliche delle testate (OSINT)

Del profilo pubblico di una testata leggiamo solo risorse che essa
**pubblica apposta per essere lette da macchine** — `/ads.txt`
(standard IAB) e i dati strutturati schema.org della homepage — più la
data della prima copia nell'Internet Archive. Nessun dato personale,
nessun servizio a pagamento, nessuna chiave; le pagine si visitano nel
rispetto di robots.txt e col nostro User-Agent. Gli indizi che ne
derivano (per esempio un conto pubblicitario condiviso) sono mostrati
**come indizi, con il link all'evidenza**, mai come accertamenti.

## Canali social delle testate

Per alcune testate il catalogo dichiara il profilo **Bluesky** o
**Mastodon** ufficiale. Da quei profili si leggono, via API pubbliche e
gratuite, solo i **metadati della scheda-link** dei post (titolo,
descrizione breve, URL dell'articolo): il testo dei post non viene
conservato, nessun dato di utenti terzi viene raccolto, e contano solo i
post che linkano il dominio della testata stessa. **X (Twitter) e
Instagram** non offrono un accesso programmatico gratuito e lecito (API a
pagamento; termini d'uso che vietano la raccolta automatica): restano
esclusi finché è così.

## Dati personali

- Il sito pubblico non traccia gli utenti: nessun cookie di profilazione,
  nessun analytics esterno, nessun font o script da CDN.
- Gli **annotatori** registrano nome utente, password (con hash PBKDF2) e
  l'orientamento auto-dichiarato. Negli export pubblici l'annotatore appare
  solo come identificativo anonimo (`a1`, `a2`…) con il suo orientamento
  dichiarato, necessario per riprodurre i calcoli.
- Le **cariche politiche dei proprietari** sono fatti pubblici tratti da
  registri e fonti pubbliche, sempre con evidenza citata.

## Licenze del progetto

- Codice: **AGPL-3.0-only** (`LICENSE`). Chi eroga il servizio, anche
  modificato, deve rendere disponibili i sorgenti.
- Dati derivati (story, coperture, segnali, annotazioni anonime):
  **CC BY-SA 4.0**, esportabili da `/dati`.
- Attribuzioni di dati e librerie di terze parti: `NOTICE`.

## Richieste di rimozione

Un editore che non voglia comparire nell'aggregatore può chiederne la
disabilitazione aprendo una issue nel repository: la fonte viene
disabilitata con motivazione visibile (stesso meccanismo usato per ANSA),
mantenendo la trasparenza sul catalogo.
