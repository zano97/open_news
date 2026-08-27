"""Scarica i modelli di traduzione Argos per le lingue dell'interfaccia.

Richiede l'extra [translate] (`pip install -e ".[translate]"`). I modelli
sono open source e vengono scaricati una sola volta dall'indice pubblico di
Argos Open Tech, poi tutto funziona offline. Da eseguire al setup:

    docker compose exec worker python -m scripts.fetch_translation_models

Coppie installate: tutte quelle disponibili tra it, en, fr, de, es
(alcune coppie passano per l'inglese: è il funzionamento normale di Argos).
"""

from core.i18n import SUPPORTED_LOCALES


def main() -> None:
    try:
        import argostranslate.package  # type: ignore[import-not-found]
    except ImportError:
        print(
            "argostranslate non installato. Installa l'extra: "
            'pip install -e ".[translate]" e rilancia.'
        )
        raise SystemExit(1) from None

    print("Aggiorno l'indice dei pacchetti Argos…")
    argostranslate.package.update_package_index()
    available = argostranslate.package.get_available_packages()
    wanted = set(SUPPORTED_LOCALES)
    installed = 0
    for package in available:
        if package.from_code in wanted and package.to_code in wanted:
            print(f"Installo {package.from_code} → {package.to_code}…")
            argostranslate.package.install_from_path(package.download())
            installed += 1
    print(
        f"Fatto: {installed} coppie installate. Il worker inizierà a tradurre "
        "i titoli neutri al prossimo ciclo (ogni 15 minuti)."
    )


if __name__ == "__main__":
    main()
