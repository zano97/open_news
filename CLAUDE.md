# Open News — istruzioni per Claude Code

## Git: identità e convenzioni (OBBLIGATORIE)

- **Autore dei commit**: sempre il proprietario del repo, mai un'identità
  Claude/bot. Prima di qualsiasi commit esegui:

  ```bash
  git config user.name "zano97"
  git config user.email "miky24397@gmail.com"
  ```

- **Niente riga `Co-Authored-By: Claude ...`** e niente altre firme o link
  di sessione Claude nei messaggi di commit, nei titoli o nei corpi delle
  PR: è una scelta esplicita del proprietario (vedi anche
  `.claude/settings.json` → `includeCoAuthoredBy: false`).
- Messaggi di commit in italiano, descrittivi.
- Il lavoro si sviluppa su un branch e si porta su `main` con merge
  **fast-forward only**; si pusha su `main` solo a lavoro verde.

## Qualità prima di ogni commit

```bash
make check      # ruff + mypy --strict + pytest (coverage core >= 80%)
make test-e2e   # se hai toccato template, CSS o JS
```

## Contesto essenziale

- App: aggregatore di notizie che misura e mostra il bias (vedi README.it.md).
- Solo software libero e risorse gratuite: MAI API a pagamento o chiavi di
  servizi commerciali (un test lo impone).
- Tutte le richieste HTTP passano da `core/net.py` (allowlist egress).
- Vincoli legali in `docs/LEGAL.md`: in pagina solo titolo+snippet(≤200)+link;
  il testo integrale è solo per uso interno, mai mostrato né esposto.
- Le decisioni architetturali si registrano in `docs/DECISIONS.md` (ADR).
- Interfaccia in 5 lingue: ogni stringa nuova va in TUTTI i cataloghi
  `apps/web/translations/*.yaml` (un test impone la parità delle chiavi).
