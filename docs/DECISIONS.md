# Decisioni architetturali (ADR)

Registro delle decisioni, in ordine cronologico. Ogni decisione ambigua viene
risolta scegliendo l'opzione più semplice e più trasparente, e annotata qui.

---

## ADR-0001 — Licenza AGPL-3.0, dati derivati CC BY-SA 4.0

**Contesto.** Il repository conteneva un `LICENSE` MIT segnaposto creato alla
nascita del repo. Il progetto richiede AGPL-3.0.
**Decisione.** `LICENSE` sostituito con il testo integrale AGPL-3.0-only
(fonte: SPDX license-list-data). I dati derivati (etichette, mappe di
copertura, segnali aggregati) sono pubblicati in CC BY-SA 4.0, dichiarato in
`NOTICE` e nella pagina `/dati`.
**Conseguenze.** Chi eroga il servizio modificato deve pubblicare i sorgenti
(clausola network della AGPL): coerente con la missione di trasparenza.

## ADR-0002 — Layout del repository: package `core/` e `apps/`

**Decisione.** Struttura a package top-level `core/` (dominio: modelli,
ingestione, NLP, cluster, bias, provenance) e `apps/` (API+web, worker), come
da specifica di progetto. Installazione con `pip install -e .`; niente
`src/`-layout per mantenere gli import identici a come appaiono nel repo.

## ADR-0003 — PostgreSQL 16 + pgvector in produzione, SQLite nei test

**Contesto.** Serve un solo DB per dati relazionali e vettori; i test devono
girare ovunque senza servizi esterni.
**Decisione.** Tipi di colonna portabili (`core/models/types.py`):
`EmbeddingVector` è `vector(768)` su PostgreSQL e JSON testuale su SQLite;
`TZDateTime` garantisce datetime sempre timezone-aware UTC su entrambi;
JSON è `JSONB` su PostgreSQL. La KNN nativa esiste solo su PostgreSQL; su
SQLite la similarità si calcola in Python (adeguato ai volumi dei test).
**Conseguenze.** Nessun mock del DB nei test; lo stesso codice gira su
entrambi i backend.

## ADR-0004 — Migrazione iniziale da metadati, migrazioni successive incrementali

**Decisione.** La migrazione Alembic `0001` crea lo schema con
`Base.metadata.create_all` (unica fonte di verità allo stato iniziale) più
`CREATE EXTENSION vector` e l'indice HNSW. Le migrazioni successive saranno
scritte a mano, incrementali.
**Motivo.** Evita la duplicazione integrale dello schema a mano in fase 0 e
il rischio di divergenza modelli/migrazione; il costo (non poter fare
`downgrade` parziale della 0001) è accettabile per un progetto nuovo.

## ADR-0005 — HTMX self-hosted; niente Alpine.js

**Decisione.** HTMX 2.0.4 è vendorizzato in `apps/web/static/js/htmx.min.js`
(licenza 0BSD/BSD — vedi NOTICE). Alpine.js non viene usato: le poche
interazioni (tema notturno, reel) sono vanilla JS/Web Components e tutto
degrada bene senza JavaScript.
**Motivo.** Meno dipendenze, CSP severa senza CDN esterni, requisito "il reel
funziona anche senza JS".

## ADR-0006 — Verifica dei feed al setup, non in fase di build

**Contesto.** La specifica chiede feed "verificati via richiesta HTTP reale al
momento del setup". L'ambiente di sviluppo/CI ha egress limitato verso i
domini delle testate.
**Decisione.** La verifica reale è lo script idempotente
`make verify-feeds` (`scripts/verify_feeds.py`): interroga ogni feed del
catalogo, aggiorna `enabled`/`disabled_reason`/`last_checked_at` e stampa un
rapporto. Va eseguito al primo deploy e periodicamente. I test usano fixture
HTTP registrate, senza rete.

## ADR-0007 — respx al posto di vcrpy per le fixture HTTP

**Decisione.** I test di ingestione usano `respx` (mock nativo di httpx,
anche async) con corpi di risposta registrati come file in
`tests/fixtures/`. vcrpy ha un supporto fragile per httpx async.
**Conseguenze.** Le fixture sono file leggibili e diffabili nel repo.

## ADR-0008 — Doppio backend di embedding, sempre dichiarato

**Contesto.** `sentence-transformers` (e5-base) pesa centinaia di MB e
richiede download di modello: inadatto a test/CI e a macchine minime.
**Decisione.** Interfaccia unica `core/nlp/embed.py` con due backend:
`hashing` (n-gram hashing deterministico, nessun download, qualità inferiore
ma sufficiente a raggruppare titoli quasi-identici) ed `e5`
(`intfloat/multilingual-e5-base`, extra `[ml]`, raccomandato in produzione).
Il backend usato finisce in `Article.embedding_method` e nella provenance:
mai un numero senza il suo metodo.

## ADR-0009 — Python 3.12

**Decisione.** `requires-python >= 3.12`; l'immagine Docker usa
`python:3.12-slim`; mypy e ruff hanno target 3.12.

## ADR-0010 — Niente valutazioni di bias importate da terzi

**Decisione (vincolo di progetto, registrato qui per riferimento).** Le fonti
esterne (Wikidata, EurOMo, ROC AGCOM, DIE) si usano solo per fatti
verificabili: proprietà, cariche, finanziamenti. Nessuna etichetta di
orientamento viene importata; il bias è calcolato dalla metodologia interna
(docs/METHODOLOGY.md) su quattro livelli mostrati separatamente, mai sommati
in un punteggio unico.

## ADR-0011 — SimHash implementato in casa

**Decisione.** Il dedup dei quasi-duplicati usa un SimHash a 64 bit scritto
nel progetto (shingle di 2 parole, blake2b) invece della dipendenza
`datasketch` (MinHash) indicata come opzione: meno dipendenze, stesso
risultato per il caso d'uso (titoli quasi identici), test dedicati.

## ADR-0012 — Embedder hashing v2 e soglia di clustering 0.18 con doppio criterio

**Contesto.** La calibrazione su 100 coppie annotate ha mostrato che (a) la
variante unigrammi+bigrammi era debole sulle parafrasi (F1 0.67) e (b) una
soglia bassa con centroide incrementale produce concatenazione: il centroide
"deriva" e attira eventi diversi.
**Decisione.** Embedder `hashing-ngram-v2` (parole piene senza stopword +
4/5-grammi di caratteri; F1 0.82 pairwise) e soglia 0.18 (precisione 0.86,
richiamo pairwise 0.51) con **doppio criterio**: similarità col centroide E
con almeno un articolo membro. Si privilegia la precisione: un merge
sbagliato inquina i confronti tra testate, una story frammentata al massimo
sottostima la copertura. Numeri pubblici in METHODOLOGY.md; con backend e5
la soglia va ricalibrata (`make calibrate`).

## ADR-0013 — "Orientamenti dichiarati diversi" = almeno 2 fasce su 3

**Contesto.** La regola di pubblicazione del livello 4 richiede annotatori
con orientamenti dichiarati "diversi", da precisare operativamente.
**Decisione.** L'auto-dichiarazione (−2..+2) è divisa in tre fasce
(< −0.5, −0.5..0.5, > 0.5); un'etichetta esce solo se gli annotatori
coprono almeno due fasce, e la media è pesata per fascia (nessuna fascia
domina per numerosità). Interpretazione documentata in METHODOLOGY.md §4.

## ADR-0014 — Entità con euristica dichiarata, QID mai indovinati

**Decisione.** Le entità delle story si estraggono con un'euristica sulle
maiuscole ricorrenti nei titoli (`entities-heuristic-v1`); il collegamento a
Wikidata avviene in un job separato best-effort e l'interfaccia mostra
"(non collegata)" finché il QID non è verificato. Con l'extra [ml]
(spaCy/GLiNER) la qualità sale, il metodo resta dichiarato.


## ADR-0015 — Demo offline con testate dimostrative, mai titoli inventati su testate reali

**Contesto.** Serve un modo per provare l'interfaccia senza rete
(`make seed-demo`), ma inventare titoli e attribuirli a testate vere
violerebbe la missione del progetto.
**Decisione.** La modalità `--offline-demo` crea 8 testate esplicitamente
"(demo)" con dominio `.invalid` e `terms_note` che dichiara l'origine
inventata delle notizie; le testate reali del catalogo non ricevono mai
contenuti inventati.

## ADR-0016 — Interfaccia multilingua con cataloghi YAML e scelta esplicita

**Contesto.** L'interfaccia deve parlare più lingue; i framework gettext/.po
aggiungono una toolchain pesante per ~180 stringhe.
**Decisione.** Cataloghi YAML piatti in `apps/web/translations/{it,en,fr,de,es}.yaml`
con l'italiano come riferimento; `core/i18n.py` fornisce `t()` con fallback
lingua → inglese → italiano → chiave (mai una pagina rotta). Un test
garantisce parità di chiavi e di segnaposto tra le lingue. La lingua si
sceglie SOLO esplicitamente dal selettore in testata (cookie, rotta
`/lingua/{code}` con guardia anti open-redirect): niente auto-rilevamento
dall'Accept-Language, per avere un comportamento deterministico e testabile.
Le date della testata sono localizzate; i contenuti delle notizie restano
nella lingua delle testate; i documenti lunghi (metodologia) esistono in
it/en con fallback inglese dichiarato per le altre lingue.

## ADR-0017 — PixelRAG valutato: non adottato per l'estrazione, interessante altrove

**Contesto.** Proposta di usare PixelRAG (StarTrail-org/PixelRAG, Apache-2.0,
Berkeley) per migliorare lo "scraping" degli articoli.
**Valutazione.** PixelRAG è retrieval visivo: renderizza pagine in screenshot
e cerca sulle immagini con un embedding Qwen3-VL fine-tuned. La nostra
pipeline ha bisogno di TESTO (lessico, attori citati, tono, embedding dei
titoli): gli screenshot non alimentano queste analisi, e il modello visivo
(2B, GPU/MPS consigliati; indici da centinaia di GB) è fuori misura per la
macchina target (4 core / 8 GB, senza GPU). L'endpoint ospitato pubblico è
un servizio esterno, contro la nostra politica self-host/allowlist.
**Decisione.** Per l'estrazione resta trafilatura. PixelRAG resta annotato
come candidato per un'estensione futura coerente con la missione: catturare
le PRIME PAGINE delle testate come immagini per studiare risalto e
gerarchia visiva delle notizie (un segnale di agenda che l'HTML non rende).

## ADR-0018 — Raccolta robusta e parallela (identità HTTP, autodiscovery, GDELT a batch)

**Contesto.** Il primo seed reale ha mostrato quattro classi di fallimento:
WAF che rifiutano l'User-Agent fuori standard (403 su ilpost, fanpage,
publico, haaretz); URL di feed spostati (404 su ilgiornale, ilfoglio) o
diventati pagine HTML (avvenire, adnkronos); GDELT in 429 dopo ~50
richieste sequenziali; e un seed sequenziale da ~10-15 minuti.

**Decisione.**
1. L'header User-Agent diventa `Mozilla/5.0 (compatible; OpenNewsBot/0.1;
   +repo)` — il formato convenzionale dei crawler dichiarati (lo stesso
   schema di Googlebot): identità esplicita, ma non "fuori standard" per i
   WAF. Le regole robots.txt vengono verificate col TOKEN `OpenNewsBot`,
   così un sito che ci vieta per nome resta rispettato (testato).
2. Un feed che risponde 404/410 o HTML fa scattare l'autodiscovery
   (`<link rel="alternate">` dalla homepage, stesso dominio, robots e rate
   limit rispettati); l'URL trovato è ricordato in `FeedState.resolved_url`.
   Un feed che fallisce 3 volte di fila entra in backoff (6 ore) nei giri
   periodici; il seed riprova sempre tutto.
3. GDELT: domini interrogati A BATCH (`(domain:a OR domain:b ...)`, 6 per
   richiesta, 250 risultati) con attribuzione per dominio; le fonti senza
   feed (Reuters, AP) mantengono la richiesta dedicata. Retry con attesa
   crescente su 429/5xx/timeout, rispettando Retry-After; le risposte non
   JSON diventano errori leggibili, mai crash.
4. `core/ingest/pipeline.py`: fetch dei feed in parallelo (semaforo, rate
   limit per host invariato) e scritture DB in sequenza dietro un lock
   (SQLite ha un solo scrittore); nel seed RSS e GDELT girano insieme.

**Conseguenze.** Primo seed da ~10-15 minuti a pochi minuti; -80% richieste
GDELT; feed che "si riparano da soli" quando una testata sposta l'URL. Il
costo è un modulo di orchestrazione in più e uno stato per-feed più ricco
(migrazione 0005).

**Alternative scartate.** Mantenere l'UA "onesto ma inconsueto" (puniva il
progetto senza informare nessuno: l'identità resta dichiarata nel nuovo
formato); imitare un browser vero (disonesto); un fetch multi-processo
(inutile: il collo è l'attesa di rete, non la CPU).

## ADR-0019 — IPv4 forzato e secondo passaggio GDELT (secondo seed reale)

**Contesto.** Il seed su macOS mostrava `ConnectTimeout` intermittenti verso
GDELT (e cbc.ca) nonostante i retry: httpx/httpcore non implementa
l'happy-eyeballs (RFC 8305), quindi su reti con IPv6 annunciato ma rotto il
connect scade sull'AAAA senza mai provare l'A record.

**Decisione.** Il client di `core/net.py` monta un transport con
`local_address="0.0.0.0"` (socket IPv4; disattivabile con
`HTTP_IPV4_ONLY=false`) e `retries=2` sui tentativi di connessione, MA solo
quando non c'è un proxy configurato: un transport esplicito disattiverebbe
il supporto `HTTPS_PROXY` di httpx, e dietro proxy è il proxy a connettersi.
Timeout di connessione a 10 s (il totale resta 20). In più
`ingest_gdelt_all` ritenta i gruppi falliti con un secondo passaggio a fine
giro, e l'autodiscovery dei feed prova i percorsi convenzionali (/feed/,
/rss, …) quando la homepage non dichiara `<link rel="alternate">`.

**Alternative scartate.** Implementare l'happy-eyeballs in casa (fuori
scala); aumentare i timeout (allunga l'attesa senza cambiare l'esito sul
percorso IPv6 rotto).

**Aggiornamento (stesso giorno).** Il terzo seed reale ha mostrato che
quando GDELT non accetta connessioni i retry costano minuti a vuoto (9
fonti solo-GDELT × tentativi × timeout). Ora gli errori di trasporto hanno
al massimo 2 tentativi rapidi (il transport ha già ritentato per conto
suo; il backoff paziente resta per i 429), e un interruttore di circuito
ferma tutto: dopo 2 gruppi consecutivi senza connessione i rimanenti si
saltano subito — li recupera il ciclo di raccolta successivo (feed ogni 10
minuti, GDELT ogni 30). Anche robots.txt ha un timeout corto (8 s): un
robots che non arriva non deve trattenere il feed per 20.

## ADR-0020 — Angoli ciechi v2: significatività, non semplice assenza

**Contesto.** La v1 marcava come "angolo cieco" ogni paese con ≥3 fonti
attive che non aveva coperto una story con ≥5 testate. Con un catalogo di
~60 paesi quasi ogni story risultava "cieca" per decine di paesi: rumore
sistematico, e la sensazione (fondata) di inaffidabilità.

**Decisione.** La v2 (`blindspot-country-v2`) marca solo l'assenza
IMPROBABILE: per ogni testata si stima la propensione a coprire le grandi
story nella finestra; un paese è marcato solo se Π(1−propensione) delle sue
testate attive è < 5%, su story mature (≥6 h), internazionali (≥3 paesi),
con gruppi ≥3 testate; al lettore i 3 paesi più significativi, con la
probabilità nel dato. I flag vecchi vengono azzerati quando le condizioni
non valgono più. Le soglie sono costanti di metodo (non modificabili dal
pannello), documentate su /metodo.

**Conseguenze.** Un paese piccolo, che copre poco di suo, non raggiunge mai
la significatività: sparisce il rumore. Il badge torna a voler dire
qualcosa: "questa assenza non è spiegabile col caso". Il segnale per-fonte
(confronto coi pari dello stesso paese) resta invariato.

## ADR-0021 — Rifinitura dell'interfaccia: identità d'epoca, esecuzione moderna

**Contesto.** L'estetica da quotidiano d'inizio Novecento è identità del
progetto (ADR di fase 5), ma l'esecuzione — filetti duri ovunque, nessuna
transizione, controlli nativi spogli, barra di avanzamento a bande —
faceva percepire l'app «vecchia e macchinosa».

**Decisione.** Si conserva l'identità (carta, Playfair/EB Garamond,
accento bronzo, filetti) e si ammoderna l'esecuzione con un layer di
token condivisi: raggi (10/6px), ombre morbide a due livelli, transizioni
160ms su colori/bordi/ombre/trasformazioni, chip per il filtro paesi
(stato attivo pieno), card con sollevamento al passaggio, campi modulo
coerenti con focus ring, badge a pastiglia, comparsa discreta del
contenuto e scorrimento fluido — tutto dietro `prefers-reduced-motion`.
La barra di aggiornamento mostra l'avanzamento REALE (feed e gruppi GDELT
contati; nel giro manuale le tre fasi sono pesate 55/35/10 così la barra
non torna mai indietro) con percentuale sull'etichetta del pulsante;
quando il progresso non è stimabile, un respiro di opacità sostituisce le
bande.

**Conseguenze.** Stessa carta, letta meglio: nessun cambio di palette o
tipografia, quindi nessun impatto su contrasti già verificati; i token
rendono coerente ogni componente futuro.

## ADR-0022 — Titoli sempre editoriali: artefatti GDELT riparati e mai preferiti

**Contesto.** I titoli raccolti via GDELT arrivano ritokenizzati alla
fonte: apostrofi persi («larte»), punteggiatura staccata («9 / 11»,
«morta , addio») e nomi di paese riscritti in inglese minuscolo anche nei
titoli non inglesi («united states erhöhen…»). Quando uno di questi
diventava titolo neutro o sottotitolo, la prima pagina mostrava titoli
storpiati; in un caso reale il sottotitolo era il titolo di un'ALTRA
notizia (articolo finito nel cluster per errore, agganciato proprio dai
token «united states» duplicati).

**Decisione.** Quattro difese complementari. (1) `tidy_title` ripara
anche i nomi di paese minuscoli (solo forme multi-parola, mai legittime
in un titolo: «united states» → «USA»); la migrazione 0007 applica la
stessa pulizia all'archivio (solo articoli con provenance GDELT) e
azzera le traduzioni fatte sui titoli storpiati. (2) Il titolo neutro
preferisce, a parità di appartenenza al cluster, gli articoli CON
snippet — quelli dal feed, col titolo editoriale intatto (metodologia
§2 aggiornata). (3) Quando il feed ufficiale porta lo stesso URL di un
articolo arrivato prima via GDELT, il titolo vero rettifica quello
storpiato (provenance `rss-rettifica-v1`); l'ETag si memorizza solo per
un feed valido, mai per una pagina anti-bot. (4) Il sottotitolo «in
lingua» deve condividere col titolo neutro almeno un nome proprio o un
numero (prefisso comune ≥4: «Governo»/«Government»): meglio nessuna riga
che la notizia sbagliata. In più, un feed che risponde 403 o 200 non
interpretabile viene ritentato UNA volta con User-Agent da browser,
sempre dopo il via libera di robots.txt (che resta consultato col nostro
nome dichiarato).

**Conseguenze.** I titoli GDELT restano senza apostrofi quando il
cluster non ha di meglio (irrecuperabili alla fonte); qualche
sottotitolo legittimo senza nomi propri condivisi sparisce finché non
arriva la traduzione automatica (rigenerata comunque entro un quarto
d'ora); i siti con filtro anti-bot ricevono al più una richiesta doppia
per giro.

## ADR-0023 — Canali social delle testate: Bluesky e Mastodon sì, X e Instagram no (per ora)

**Contesto.** Molta informazione passa ormai dai social, e l'utente vuole
che contino per notizie, copertura e angoli ciechi. Ma il progetto ha tre
vincoli non negoziabili: solo software libero e servizi gratuiti (mai API
a pagamento), solo titolo+snippet+link (docs/LEGAL.md), egress in
allowlist. E un vincolo di misura: gli indicatori contano «che cosa
pubblica quale testata in quale paese» — un post social di terzi non ha
una testata né un paese attribuibili in modo onesto.

**Decisione.** I social entrano come **canale di raccolta aggiuntivo
delle testate esistenti**, non come fonti a sé: il profilo ufficiale di
una testata è un altro posto dove la testata pubblica i PROPRI articoli.
Dei post si usano solo i metadati della scheda-link (titolo, descrizione,
URL) e contano solo i post che linkano il dominio della testata; dedup
per URL con i canali feed e GDELT. Piattaforme: **Bluesky** (AppView
pubblica senza chiave; si accettano SOLO handle a dominio verificato —
l'autenticità la garantisce il protocollo, un impostore non può entrare
per errore di configurazione) e **Mastodon** (API pubblica dell'istanza
dichiarata nel catalogo; le istanze entrano nell'allowlist solo via
catalogo). **X (Twitter) e Instagram restano esclusi**: le API sono a
pagamento e i termini vietano la raccolta automatica — non c'è oggi un
modo gratuito e lecito, e il progetto non paga API né viola termini. La
decisione si riesamina se le condizioni di accesso cambiano.

**Conseguenze.** Copertura e angoli ciechi guadagnano richiamo (un
articolo visto solo sui social conta comunque per la sua testata) senza
toccare la semantica degli indicatori; la provenance di ogni articolo
social è tracciata (`bluesky-public-api` / `mastodon-public-api`, col
link al post). Il limite è dichiarato: niente X/Instagram significa
nessuna pretesa di misurare «l'attenzione social» — misuriamo sempre e
solo che cosa pubblicano le testate.

## ADR-0024 — La prima pagina è attualità: finestra di 48 ore e copertura scontata del tempo

**Contesto.** La prima pagina ordinava le story per numero di testate su
TUTTO l'archivio, senza finestra temporale, e la scheda stampava la data
di prima apparizione. Dopo pochi giorni di raccolta l'effetto era «vedo
sempre le stesse notizie, ferme a ieri»: le story più grandi restavano in
cima per sempre e quelle nate oggi (poche testate nelle prime ore) non
entravano mai nelle 36 mostrate — pur con la raccolta perfettamente
funzionante.

**Decisione.** La prima pagina mostra solo story con `last_seen` nelle
ultime 48 ore (`front_page_window_hours`, configurabile), ordinate per
**copertura scontata del tempo**: peso = copertura × 0.5^(ore
dall'ultimo aggiornamento / 12). Regola semplice, spiegabile e
deterministica: una story enorme ma ferma decade, una ancora viva resta
su. Con filtro paese il peso usa la copertura di QUEL paese. Finestra
vuota (archivio fermo, demo datata) → si mostrano comunque le più
recenti, mai una pagina bianca. La data della scheda è `last_seen`
(l'ultimo articolo); la pagina story dichiara sia la prima apparizione
sia l'ultimo aggiornamento. I conteggi dei chip e della mappa /paesi
usano la stessa finestra, così i numeri descrivono il giornale di oggi.
In più il raggruppamento salta gli articoli che sollevano un'eccezione
invece di fermarsi: la coda è ordinata per data e un errore in testa
avrebbe bloccato per sempre l'arrivo di notizie nuove.

**Conseguenze.** /lampo aveva già la sua finestra (12 ore) e non cambia;
l'archivio resta tutto raggiungibile (pagina story, export /dati); la
metodologia («Le regole di presentazione») documenta finestra e sconto.

## ADR-0025 — Il fetch dei feed non passa da robots.txt (il crawling sì)

**Contesto.** Il primo seed reale su Mac mostrava famiglie di errori:
«robots.txt vieta l'accesso» al feed di testate che il feed lo pubblicano
apposta (il Fatto Quotidiano, Civil.ge, Ekathimerini, Axios, Times of
Israel), 403/202 da filtri anti-bot, 404 da URL migrati, e «feed vuoto o
non interpretabile» senza indizi su cosa fosse arrivato davvero.

**Decisione.** (1) Il fetch di un FEED RSS/Atom non passa più dal filtro
robots.txt: il protocollo robots governa i crawler, mentre un feed è
un'interfaccia di abbonamento pubblicata proprio per gli aggregatori che
leggono per conto dei lettori iscritti — è la prassi dei lettori di feed,
e Google Feedfetcher la documenta esplicitamente («le richieste partono
da un'azione umana, non da un crawler»; chi non vuole il fetch serve
404/410 al singolo agente). robots.txt resta rispettato per il crawling
vero: homepage (autodiscovery), pagine articolo, testo integrale; restano
sempre rate limit, cache condizionale e User-Agent identificativo, e una
testata può sempre negare il feed con 403/404 mirati, che onoriamo col
backoff. (2) Il ritento anti-bot usa l'identità browser COMPLETA
(intestazioni Accept/Accept-Language/Sec-Fetch-*), e scatta anche su 202.
(3) «Feed vuoto o non interpretabile» ora registra content-type e
anteprima del corpo: la diagnosi si legge dal log. (4) L'autodiscovery
prova più percorsi convenzionali (WordPress /?feed=rss2, Arc XP
/arc/outboundfeeds/rss/), non applica robots ai candidati (sono feed) e
ritenta i candidati bloccati con identità browser. (5) URL del catalogo
corretti da ricerca: Corriere (feed-hp restyle 2025), Adnkronos
(RSS_Ultimora/Cronaca), Il Foglio (API naxos), Le Point e El Universal
(Arc XP), Haaretz (cmlink di riserva), Kuwait Times (www); Avvenire,
Hürriyet Daily News, il Giornale e Tempo English non documentano più un
feed → feed_urls vuoti, copre GDELT senza rumore a ogni giro.

**Conseguenze.** docs/LEGAL.md aggiornato («robots.txt rispettato per il
crawling»); più feed vivi al primo avvio; i 403 da fingerprinting TLS
(La Stampa) restano non risolvibili onestamente e coperti da GDELT.

## ADR-0026 — Clustering a lotti con indice in memoria: il seed non sembra mai bloccato

**Contesto.** Col catalogo rimpolpato e i feed sbloccati, il primo seed
reale ha portato ~1400 articoli in un colpo. La fase di analisi dopo la
raccolta girava senza tetto di tempo e senza output, e su SQLite il KNN
rileggeva e decodificava TUTTI i centroidi dal database per OGNI
articolo; in più il titolo neutro veniva ricalcolato a ogni aggancio
ricaricando tutti gli articoli della story (quadratico sulle story
grandi). Risultato: installazione che «si blocca» dopo la raccolta.

**Decisione.** (1) ``StoryIndex``: i centroidi si caricano UNA volta in
una matrice numpy (numpy è già dipendenza core) e ogni ricerca è un
prodotto matrice-vettore; gli embedding dei membri per il doppio
criterio si caricano una volta per story e si aggiornano in memoria.
(2) Nel clustering a lotti il titolo neutro si ricalcola UNA volta per
story toccata, a fine giro. (3) ``cluster_pending`` accetta un
``deadline`` (si ferma con garbo, il resto resta in coda) e un callback
di avanzamento. (4) Il seed stampa l'avanzamento («raggruppati X/Y») e
applica il budget di tempo anche all'analisi; il cluster_job del worker
ha una deadline di 8 minuti, sotto il proprio intervallo. Benchmark sul
caso peggiore (1400 articoli tutti nella stessa story, SQLite):
da 211 a 10 secondi; il metodo non cambia (un test impone che l'indice
dia gli stessi vicini della ricerca su DB).

**Conseguenze.** Il primo avvio resta nei minuti promessi anche con
migliaia di articoli; un arretrato enorme si smaltisce in più giri da
10 minuti invece di accavallare i job; su PostgreSQL l'indice sostituisce
pgvector solo dentro il giro a lotti (finestra temporale, centinaia di
story: il matvec è comunque immediato).
