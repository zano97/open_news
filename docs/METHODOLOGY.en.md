# How we compute it

This page explains **every number and every label** you see on Open News:
where the data comes from, how we compute it, and when we decide **not** to
show a figure because it is not solid enough. It is written for people
without a technical background; the code implementing everything you read
here is open and verifiable in the repository.

**The guiding principle**: media bias is not a single number. We give no
"report cards". We measure different things on **four separate levels**,
from the most objective to the most interpretive, and we always show them
separately, each with its source, the date of computation and the method
version. When a figure is missing we write "data not available": never an
undeclared estimate.

---

## Level 1 — Structure: who owns and who funds (facts)

**What we show.** For every outlet: who owns it (including corporate
chains), the political offices held by its owners, the public subsidies
received per year, and the editorial line the outlet itself declares
(quoted verbatim, with a link).

**Where the data comes from.** Only verifiable sources:

- **ROC** — the Italian register of communication operators (AGCOM);
- **EurOMo** — the Euromedia Ownership Monitor (CC BY 4.0 data);
- **Wikidata** (CC0) — only for corporate facts: owner, founder, publisher.
  We **never** import properties such as "political alignment": at most the
  interface may quote a fact "according to Wikidata", linking the entity;
- **The Italian Department for Information and Publishing** — public lists
  of direct press subsidies (Pluralism Fund).

Every row carries the name of the evidence, the link and the date it was
recorded. When we do not know a shareholding or an amount, the field says
"data not available" with a note on where to verify it. The source data
lives in public files in the repository and is corrected via pull request,
so every change stays tracked and signed.

## Level 2 — Selection: what it covers and what it ignores (statistics)

There is no label decided by us here: these are counts over what the
outlets publish. First we group articles into **stories** (the same event
told by different outlets), then we measure three things.

### Grouping into stories

Every article is turned into a numeric vector (*embedding*) from its
headline and snippet. A new article joins the most similar story seen in
the last **72 hours** if it passes a **double criterion**: it must resemble
the *centre* of the group **and** at least one real article inside it (the
centre alone "drifts" as the group grows and would end up attracting
everything). Otherwise it opens a new story. The story's "neutral" headline
is not generated: it is the **real headline closest to the centre of the
group**, preferring — membership being equal — articles that arrived from
the outlet's own feed: headlines collected via GDELT are re-tokenised at
the source (lost apostrophes, reassembled punctuation, rewritten country
names) and are used only when the group has nothing better.

The threshold is not arbitrary: we **calibrated it on 100 hand-annotated
headline pairs** (50 same-event pairs, 50 different-event pairs, 25 of them
"hard": same topic, different event). The set is public in
`data/seeds/calibration_pairs.yaml`. With the default embedding engine
(`hashing-ngram-v2`, which downloads no models) the chosen threshold is
**0.18**: on pairs taken one by one it yields **precision 0.86** and recall
0.51 (same-language). We chose to favour precision: wrongly merging two
different events pollutes the comparisons between outlets, while a
fragmented story at worst underestimates coverage. The effective recall of
the clustering is higher than the pairwise figure, because it is enough for
**one** of the phrasings to pass the threshold for the others to attach
through the group. The known limit remains: cross-language pairs attach
mostly when they share proper names. In production we recommend the
multilingual engine `e5` (`intfloat/multilingual-e5-base`), for which the
threshold must be recalibrated with `make calibrate`
(`scripts/calibrate_threshold.py`).

A story is a "**flash**" if at least **5 outlets** cover it within **2
hours** of its first appearance.

**The story in brief.** The articles' full text belongs to the outlets and
is never shown (see the legal notes). If the instance enables the optional
local model (Ollama), the story page offers a "Generate the story in brief"
button: the **neutral summary** is generated **only when the reader asks**,
locally, from the public headlines and excerpts only, with the answer
streaming in live; once generated it is saved, always **marked as
automatic**, with the model recorded in the provenance. The summary
describes the event and never judges the outlets; the original articles,
linked next to it, are authoritative.

### <a id="agenda"></a>The agenda profile

We classify every story into one of **20 fixed topics** (domestic politics,
immigration, climate, sport…) with a deliberately simple method: public
keyword lists per topic and per language (`data/topics.yaml`, extensible
via pull request). Then, for each outlet over a 30-day window, we compare
its topic distribution with the **average across outlets**: "it talks about
immigration 8 percentage points more than average".

How solid is that number? We check it with the **bootstrap**: we resample
the outlet's articles 200 times and compute a 95% confidence interval. If
the interval contains zero, the interface says "within noise"; otherwise
"solid". A minimum of **10 articles with a topic** in the window is
required, otherwise: "under evaluation".

### The co-coverage map

We build a table: rows = outlets, columns = stories (covered by at least 2
outlets), 1 if the outlet covered the story. With principal component
analysis (PCA) we project everything onto two dimensions: **outlets that
cover the same stories end up close together**.

Mind the most important point: **the axes of the map have no predefined
meaning**. They are not "left/right": they emerge from the data. That is
why next to the map we always show **the 10 stories that pull each axis
hardest** in each direction: they are what separates the outlets in that
period. The variance explained by each dimension is stated below the map.

### Blind spots

For each outlet: the stories covered by **at least 50% of the other active
outlets from the same country** but not by it.

For each story, the "blind spot" badge follows a **significance test**
(method `blindspot-country-v2`): not covering is NOT enough — for a small
country it is the norm, not a choice. For every outlet we estimate its
*propensity* to cover big stories (share of the window's stories with ≥5
outlets it covered); a country is flagged only when the probability that
NONE of its active outlets would cover the story by pure chance —
Π(1−propensity) — is **below 5%**, and only for mature stories (≥6 hours),
international ones (≥3 countries), with groups of ≥3 active outlets. At
most the 3 most significant countries are shown, with the probability
recorded in the data. The test does not say *why* a country ignored a
piece of news: it records that the absence is statistically unlikely.

## Level 3 — Framing: how it tells the news (lexical)

### <a id="framing"></a>The lexicon

Different words for the same thing carry different judgements: in Italian,
"clandestini", "irregolari" and "migranti" are not neutral synonyms. We
maintain a **public lexicon** of term groups sharing the same denotation
with different connotations (`data/lexicon_it.yaml`: 51 Italian groups;
`data/lexicon_en.yaml`: 26 English ones). Every entry declares its
rationale, who added it and any references (for migration, for instance,
the Carta di Roma). We count how often each outlet uses each term (with
regular inflections) in headlines, snippets and — for internal analysis
only, never republished — full text. We show counts, not judgements. The
lexicon grows via pull request: if an entry looks wrong to you, propose a
change.

### Who gets to speak

With a declared heuristic (`actors-heuristic-v1`) we detect quoted speech
and who utters it, and classify the role: government, opposition,
institution, expert, citizen, company. The per-outlet aggregate answers a
precise question: **who is handed the microphone?** It is a heuristic: its
precision is not that of a human annotator, which is why the method is
written next to the figure.

### Tone

A small public lexicon of valence words (fear, massacre, victory,
agreement…) classifies every **headline** as negative, neutral or positive.
We only show the **distribution per outlet** ("42% negative headlines"),
never the judgement on a single article: that would be too fragile.

## <a id="livello4"></a>Level 4 — Positioning: human judgement with a protocol

The only level where human beings express a judgement, and for that reason
the most protected by rules.

**Blind annotation.** Annotators see only headline and snippet: **they do
not know which outlet** the content comes from, and see no URL or images.
They judge on two separate axes, never a single one:

- **economic axis**: −2 (more public intervention) ↔ +2 (more market);
- **cultural axis**: −2 (progressive) ↔ +2 (conservative);
- or "not applicable" if the text takes no position.

**Declared annotators.** Every annotator declares their own orientation on
the same two axes. The declaration serves two purposes: verifying that
labels arise from agreement between people with **different** orientations
(we split declarations into three brackets) and weighting the average so
that no bracket dominates by headcount.

**Publication rules.** A label for an outlet is published only if, for that
axis:

1. at least **50 articles** of the outlet have been annotated;
2. at least **3 annotators** took part, spanning at least **2 different
   declared-orientation brackets**;
3. inter-annotator agreement, measured with **Krippendorff's alpha**
   (ordinal metric, implemented and tested in the repository), is **≥ 0.6**.

Otherwise the interface shows "under evaluation (n/50 articles, k
annotators)" with the exact list of what is missing. The alpha is public.

**Automatic estimates (optional).** Once there are enough annotations, a
model trained **only on those annotations** may extend coverage. Its
predictions: are used only aggregated per outlet, never on a single
article; are marked "automatic estimate"; carry the cross-validated error
next to them. The model is never the judge of bias: it learns from the
human protocol and inherits its limits.

---

## Presentation rules

- No red/blue colours suggesting a moral judgement: the palette is paper
  and ink.
- Every number has a **provenance** record: method, version, inputs, date
  of computation. You find it at the bottom of pages ("Where does this data
  come from?") and in the exports.
- Signals are recomputed **every week** and stay dated: history is never
  overwritten.
- The four levels are **never summed** into a single score.

## What can go wrong (known limits)

We are transparent about this too:

- the **clustering** is wrong roughly 2 times out of 10 (see the
  calibration figures above): sometimes it splits the same event, sometimes
  it merges neighbouring events;
- the **topic classifier** is keyword-based: it understands "landings" but
  may miss a metaphor;
- the extraction of **who speaks** is a heuristic over quotation marks and
  capital letters;
- the **lexicon** counts do not understand irony or scare quotes;
- **language detection** and **entities** have better versions that can be
  enabled with the `[ml]` extra (open models downloaded locally).

Every improvement goes through the repository, with the method version
changing and the history preserved.

## Licences

The software is AGPL-3.0. The **derived data** (labels, coverage, signals)
is published under **CC BY-SA 4.0** at [/dati](/dati). Headlines and
snippets remain the property of their outlets: we show only the minimum for
quotation, with a link to the source (see the legal notes in the
repository, `docs/LEGAL.md`).
