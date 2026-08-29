# Come lo calcoliamo

Questa pagina spiega **ogni numero e ogni etichetta** che vedi su Open News:
da dove vengono i dati, come li calcoliamo, e quando decidiamo di **non**
mostrare un dato perché non è abbastanza solido. È scritta per chi non ha un
background tecnico; il codice che implementa quello che leggi qui è aperto e
verificabile nel repository.

**Il principio guida**: il bias dell'informazione non è un numero unico. Non
diamo "pagelle". Misuriamo cose diverse su **quattro livelli separati**, dal
più oggettivo al più interpretativo, e li mostriamo sempre separati, ognuno
con la sua fonte, la data del calcolo e la versione del metodo. Se un dato
manca, scriviamo "dato non disponibile": mai una stima non dichiarata.

---

## Livello 1 — La struttura: chi possiede e chi finanzia (fatti)

**Che cosa mostriamo.** Per ogni testata: chi la possiede (con le catene
societarie), le cariche politiche ricoperte dai proprietari, i finanziamenti
pubblici ricevuti per anno, e la linea editoriale che la testata stessa
dichiara (citata testualmente, con link).

**Da dove vengono i dati.** Solo da fonti verificabili:

- **ROC** — il Registro degli Operatori di Comunicazione dell'AGCOM;
- **EurOMo** — Euromedia Ownership Monitor (dati CC BY 4.0);
- **Wikidata** (CC0) — solo per fatti societari: proprietario, fondatore,
  editore. **Non** importiamo mai proprietà come "orientamento politico":
  al massimo citiamo un fatto "secondo Wikidata", con link all'entità;
- **Dipartimento per l'informazione e l'editoria** — elenchi pubblici dei
  contributi diretti (Fondo per il pluralismo).

Ogni riga ha accanto il nome dell'evidenza, il link e la data di
rilevamento. Se non conosciamo una quota societaria o un importo, il campo
dice "dato non disponibile" con una nota su dove verificarlo. I dati di
partenza vivono in file pubblici del repository e si correggono via pull
request, così ogni modifica resta tracciata e firmata.

### Tracce pubbliche: quello che la testata pubblica di sé

Oltre ai registri, leggiamo tre segnali che la testata stessa espone
(o che espone il web), tutti gratuiti e senza chiavi:

- **`ads.txt`** — il file, standard del settore pubblicitario, con cui
  un editore dichiara chi è autorizzato a vendere i suoi spazi e con
  quale numero di conto. Dice **chi la finanzia**; e quando due testate
  «indipendenti» dichiarano lo **stesso conto diretto** presso la stessa
  rete, i loro incassi finiscono nello stesso posto: è un indizio
  pubblico di gestione comune (mai una prova di proprietà — lo diciamo
  in pagina, con il link al file).
- **Dati strutturati di trasparenza** (`NewsMediaOrganization` di
  schema.org, vocabolario nato dal Trust Project) — quali impegni la
  testata dichiara in modo leggibile da una macchina: proprietà e
  finanziamenti, codice etico, rettifiche, diversità, redazione. Noi
  **contiamo gli impegni dichiarati e mostriamo i link**: non valutiamo
  il contenuto di quelle pagine, che ognuno può leggere.
- **Prima copia negli archivi del web** (Internet Archive) — l'età reale
  del sito, da confrontare con quella dichiarata.

L'assenza di questi dati non è un demerito: `ads.txt` non è
obbligatorio e gli impegni schema.org sono più diffusi nel mondo
anglosassone. Sono tessere, non voti.

## Livello 2 — La selezione: che cosa copre e che cosa ignora (statistica)

Qui non c'è nessuna etichetta decisa da noi: sono conteggi su quello che le
testate pubblicano. Prima raggruppiamo gli articoli in **story** (lo stesso
evento raccontato da testate diverse), poi misuriamo tre cose.

### Da dove arrivano gli articoli

Tre canali, tutti gratuiti e documentati, tutti con la stessa impronta:
titolo + snippet breve + link, dedup per URL.

1. **I feed RSS/Atom** delle testate (il canale principale).
2. **GDELT DOC 2.0**, che vede anche articoli assenti dai feed.
3. **I canali social UFFICIALI delle testate** — per ora Bluesky e
   Mastodon, le piattaforme con API pubbliche, gratuite e senza chiave.
   Dei post si usano solo i metadati della scheda-link (titolo,
   descrizione, URL) e contano SOLO i post che linkano il dominio della
   testata stessa: il profilo social è un altro posto dove la testata
   pubblica i propri articoli, mai una fonte di contenuti di terzi. Su
   Bluesky si accettano solo account con **handle a dominio verificato**
   (l'handle è il dominio della testata: l'autenticità la garantisce il
   protocollo). **X (Twitter) e Instagram restano fuori** finché non
   offrono un accesso programmatico gratuito e lecito: le API sono a
   pagamento e i termini d'uso vietano la raccolta automatica — e questo
   progetto non paga API né viola termini (ADR-0023).

Più canali per la stessa testata significano più richiamo: la copertura
per paese e gli angoli ciechi diventano più fedeli, perché un articolo
visto solo sui social entra comunque nel conteggio della sua testata.

### Il raggruppamento in story

Ogni articolo viene trasformato in un vettore numerico (*embedding*) a
partire da titolo e snippet. Un articolo nuovo si aggancia alla story più
simile vista nelle ultime **72 ore** se supera un **doppio criterio**: deve
somigliare al *centro* del gruppo **e** ad almeno un articolo reale che ne
fa parte (il centro, da solo, "deriva" man mano che il gruppo cresce e
finirebbe per attirare tutto). Altrimenti apre una story nuova. Il titolo
"neutro" della story non è generato: è il **titolo reale più vicino al
centro del gruppo**, preferendo — a parità di appartenenza — gli articoli
arrivati dal feed della testata: i titoli raccolti via GDELT sono
ritokenizzati alla fonte (apostrofi persi, punteggiatura ricomposta, nomi
di paese riscritti) e vengono usati solo quando il gruppo non ha di meglio.

La soglia non è arbitraria: l'abbiamo **calibrata su 100 coppie di titoli
annotate a mano** (50 coppie sullo stesso evento, 50 su eventi diversi, di
cui 25 "difficili": stesso tema, evento diverso). Il set è pubblico in
`data/seeds/calibration_pairs.yaml`. Con il motore di embedding di default
(`hashing-ngram-v2`, che non richiede modelli scaricati) la soglia scelta è
**0,18**: sulle coppie prese una a una dà **precisione 0,86** e richiamo
0,51 (monolingua). Abbiamo scelto di privilegiare la precisione: unire per
errore due eventi diversi inquina i confronti tra testate, mentre una story
frammentata al massimo sottostima la copertura. Il richiamo effettivo del
clustering è più alto di quello misurato a coppie, perché basta che **una**
delle formulazioni superi la soglia perché le altre si aggancino attraverso
il gruppo. Il limite noto resta: le coppie in lingue diverse si agganciano
soprattutto se condividono nomi propri. In produzione consigliamo il motore
multilingue `e5` (`intfloat/multilingual-e5-base`), col quale la soglia va
ricalibrata con `make calibrate` (`scripts/calibrate_threshold.py`).

Una story è "**lampo**" se almeno **5 testate** la coprono entro **2 ore**
dalla prima apparizione.

**Il fatto in breve.** Il testo integrale degli articoli appartiene alle
testate e non viene mai mostrato (vedi le note legali). Se l'istanza attiva
il modello locale opzionale (Ollama), la pagina della story offre un
pulsante «Genera il fatto in breve»: il **riassunto neutro** viene generato
**solo su richiesta del lettore**, in locale, dai soli titoli ed estratti
pubblici, con la risposta che compare in diretta; una volta generato resta
salvato, sempre **marcato come automatico**, con il modello registrato
nella provenienza. Il riassunto descrive l'evento e non giudica mai le
testate; a fare fede sono gli articoli originali, linkati accanto.

### <a id="agenda"></a>Il profilo di agenda

Classifichiamo ogni story in uno di **20 temi fissi** (politica interna,
immigrazione, clima, sport…) con un metodo dichiaratamente semplice: liste
pubbliche di parole chiave per tema e per lingua (`data/topics.yaml`,
ampliabili via pull request). Poi, per ogni testata e per una finestra di 30
giorni, confrontiamo la sua distribuzione dei temi con la **media delle
testate**: "parla di immigrazione 8 punti percentuali più della media".

Quanto è solido quel numero? Lo verifichiamo col **bootstrap**: ricampioniamo
200 volte gli articoli della testata e calcoliamo un intervallo di confidenza
al 95%. Se l'intervallo contiene lo zero, l'interfaccia dice "entro il
rumore"; altrimenti "solido". Serve un minimo di **10 articoli con tema**
nella finestra, altrimenti: "in valutazione".

### La mappa di co-copertura

Costruiamo una tabella: righe = testate, colonne = story (coperte da almeno
2 testate), 1 se la testata ha coperto la story. Con l'analisi delle
componenti principali (PCA) proiettiamo tutto su due dimensioni: **le testate
che coprono le stesse story finiscono vicine**.

Attenzione al punto più importante: **gli assi della mappa non hanno un
significato prefissato**. Non sono "destra/sinistra": emergono dai dati.
Per questo accanto alla mappa mostriamo sempre **le 10 story che più
"tirano" ciascun asse** in ciascun verso: sono loro a dire che cosa separa
le testate in quel periodo. La varianza spiegata da ciascuna dimensione è
indicata sotto la mappa.

### Gli angoli ciechi (blind spot)

Per ogni testata: le story coperte da **almeno il 50% delle altre testate
attive dello stesso paese** ma non da lei.

Per ogni story il badge "angolo cieco" segue un **test di significatività**
(metodo `blindspot-country-v2`): non coprire NON basta — per un paese
piccolo è la norma, non una scelta. Per ogni testata stimiamo la
*propensione* a coprire le grandi story (quota delle story con ≥5 testate
coperte nella finestra); un paese viene marcato solo se la probabilità che
NESSUNA delle sue testate attive coprisse la story per puro caso —
Π(1−propensione) — è **sotto il 5%**, e solo per story mature (≥6 ore),
internazionali (≥3 paesi), con gruppi di ≥3 testate attive. Si mostrano al
massimo i 3 paesi più significativi, con la probabilità registrata nel
dato. Il test non dice *perché* un paese ha ignorato una notizia: registra
che l'assenza è statisticamente improbabile.

## Livello 3 — Il framing: come la racconta (lessicale)

### <a id="framing"></a>Il lessico

Parole diverse per la stessa cosa portano giudizi diversi: "clandestini",
"irregolari" e "migranti" non sono sinonimi neutri. Manteniamo un **lessico
pubblico** di gruppi di termini con la stessa denotazione e connotazione
diversa (`data/lexicon_it.yaml`: 51 gruppi italiani; `data/lexicon_en.yaml`:
26 inglesi). Ogni voce dichiara la motivazione, chi l'ha aggiunta e le
eventuali fonti (per l'immigrazione, ad esempio, la Carta di Roma). Contiamo
quante volte ogni testata usa ciascun termine (con le flessioni regolari:
"clandestino/clandestini") in titoli, snippet e — solo per l'analisi interna,
mai ripubblicato — testo integrale. Mostriamo i conteggi, non un giudizio.
Il lessico cresce via pull request: se una voce ti sembra sbagliata, proponi
la modifica.

### Chi lascia parlare

Con un'euristica dichiarata (`actors-heuristic-v1`) individuiamo il discorso
riportato tra virgolette e chi lo pronuncia, e classifichiamo il ruolo:
governo, opposizione, istituzione, esperto, cittadino, azienda. L'aggregato
per testata risponde a una domanda precisa: **a chi viene dato il
microfono?** È un'euristica: la precisione non è quella di un annotatore
umano, e per questo il metodo è scritto accanto al dato.

### Il tono

Un piccolo lessico pubblico di parole con valenza (paura, strage, vittoria,
accordo…) classifica ogni **titolo** come negativo, neutro o positivo.
Mostriamo solo la **distribuzione per testata** ("42% di titoli negativi"),
mai il giudizio sul singolo articolo: sarebbe troppo fragile.

## <a id="livello4"></a>Livello 4 — Il posizionamento: giudizio umano con protocollo

L'unico livello in cui esseri umani esprimono un giudizio, ed è per questo
il più protetto da regole.

**Annotazione cieca.** Chi annota vede solo titolo e snippet: **non sa da
quale testata provenga** il contenuto, non vede URL né immagini. Valuta su
due assi separati, mai su uno solo:

- **asse economico**: −2 (più intervento pubblico) ↔ +2 (più mercato);
- **asse culturale**: −2 (progressista) ↔ +2 (conservatore);
- oppure "non applicabile" se il testo non prende posizione.

**Annotatori dichiarati.** Ogni annotatore dichiara il proprio orientamento
sugli stessi due assi. La dichiarazione serve a due cose: verificare che le
etichette nascano dall'accordo di persone con orientamenti **diversi**
(dividiamo le dichiarazioni in tre fasce) e pesare la media in modo che
nessuna fascia domini per numerosità.

**Regole di pubblicazione.** Un'etichetta per una testata viene pubblicata
solo se, per quell'asse:

1. almeno **50 articoli** della testata sono stati annotati;
2. hanno partecipato almeno **3 annotatori**, appartenenti ad almeno
   **2 fasce di orientamento dichiarato diverse**;
3. l'accordo tra annotatori, misurato con l'**alpha di Krippendorff**
   (metrica ordinale, implementata e testata nel repository), è **≥ 0,6**.

Altrimenti l'interfaccia mostra "in valutazione (n/50 articoli, k
annotatori)" con l'elenco esatto di cosa manca. L'alpha è pubblico.

**Stime automatiche (facoltative).** Quando le annotazioni saranno
abbastanza, un modello addestrato **solo su quelle annotazioni** potrà
estendere la copertura. Le sue predizioni: si usano solo aggregate per
testata, mai sul singolo articolo; sono marcate "stima automatica"; hanno
accanto l'errore misurato in cross-validation. Il modello non è mai il
giudice del bias: impara dal protocollo umano e ne eredita i limiti.

---

## Le regole di presentazione

- La prima pagina è **attualità**: mostra solo story viste nelle ultime
  **48 ore**, ordinate per copertura **scontata del tempo trascorso**
  dall'ultimo aggiornamento (la copertura dimezza ogni 12 ore). Una story
  enorme di ieri non copre per sempre una story nata oggi; una ancora
  viva resta in alto. La data sulla scheda è quella dell'**ultimo
  articolo**, non della prima apparizione. Se la finestra è vuota (nessun
  aggiornamento recente), si mostrano comunque le story più recenti.
  I conteggi dei filtri per paese e della mappa usano la stessa finestra.
- Nessun colore rosso/blu che suggerisca un giudizio morale: la palette è
  quella della carta e dell'inchiostro.
- Ogni numero ha un record di **provenienza**: metodo, versione, input,
  data del calcolo. La trovi in fondo alle pagine ("Da dove vengono questi
  dati?") e negli export.
- I segnali si ricalcolano **ogni settimana** e restano datati: lo storico
  non viene sovrascritto.
- I quattro livelli **non si sommano mai** in un punteggio unico.

## Che cosa può andare storto (limiti noti)

Siamo trasparenti anche su questo:

- il **clustering** sbaglia circa 2 volte su 10 (vedi i numeri di
  calibrazione sopra): a volte separa lo stesso evento, a volte unisce
  eventi vicini;
- il **classificatore dei temi** è a parole chiave: capisce "sbarchi" ma
  può non capire una metafora;
- l'estrazione di **chi parla** è un'euristica su virgolette e maiuscole;
- i conteggi del **lessico** non capiscono l'ironia o le virgolette di
  distanza ("i cosiddetti 'clandestini'");
- il rilevamento **lingua** e le **entità** hanno versioni migliori
  attivabili con l'extra `[ml]` (modelli open scaricati localmente).

Ogni miglioramento passa dal repository, con la versione del metodo che
cambia e lo storico che resta.

## Licenze

Il software è AGPL-3.0. I **dati derivati** (etichette, coperture, segnali)
sono pubblicati in **CC BY-SA 4.0** su [/dati](/dati). I titoli e gli
snippet restano delle rispettive testate: mostriamo solo il minimo per la
citazione, con link alla fonte (vedi le note legali nel repository,
`docs/LEGAL.md`).
