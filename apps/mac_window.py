"""Finestra nativa macOS per Open News: WKWebView con l'icona nel Dock.

Il browser in modalità `--app` mostra nel Dock l'icona del BROWSER; questa
finestra usa il WebKit di sistema (via pyobjc, extra `[mac]`) così nel Dock
compare l'emblema di Open News. Avviata dal launcher come processo separato:

    python -m apps.mac_window http://127.0.0.1:8000

Se pyobjc non è installato il launcher ripiega sulla finestra `--app` del
browser e poi sul browser normale: la finestra nativa è un di più, mai un
requisito.
"""

import importlib
import sys
from pathlib import Path
from typing import Any

ICON_PNG = Path(__file__).resolve().parent / "web/static/icons/opennews-512.png"


def _menu(appkit: Any, app: Any) -> None:
    """Barra dei menu minima: Chiudi (Cmd+Q) e Modifica (copia/incolla)."""
    menubar = appkit.NSMenu.alloc().init()

    app_item = appkit.NSMenuItem.alloc().init()
    menubar.addItem_(app_item)
    app_menu = appkit.NSMenu.alloc().init()
    app_menu.addItem_(
        appkit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
            "Chiudi Open News", "terminate:", "q"
        )
    )
    app_item.setSubmenu_(app_menu)

    edit_item = appkit.NSMenuItem.alloc().init()
    menubar.addItem_(edit_item)
    edit_menu = appkit.NSMenu.alloc().initWithTitle_("Modifica")
    for titolo, azione, tasto in (
        ("Annulla", "undo:", "z"),
        ("Taglia", "cut:", "x"),
        ("Copia", "copy:", "c"),
        ("Incolla", "paste:", "v"),
        ("Seleziona tutto", "selectAll:", "a"),
    ):
        edit_menu.addItem_(
            appkit.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(
                titolo, azione, tasto
            )
        )
    edit_item.setSubmenu_(edit_menu)

    app.setMainMenu_(menubar)


def main() -> None:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    appkit: Any = importlib.import_module("AppKit")
    foundation: Any = importlib.import_module("Foundation")
    webkit: Any = importlib.import_module("WebKit")

    app = appkit.NSApplication.sharedApplication()
    app.setActivationPolicy_(0)  # NSApplicationActivationPolicyRegular: nel Dock

    # Nome nella barra dei menu (il processo è un python qualsiasi).
    info = foundation.NSBundle.mainBundle().infoDictionary()
    if info is not None:
        info["CFBundleName"] = "Open News"

    if ICON_PNG.exists():
        icona = appkit.NSImage.alloc().initWithContentsOfFile_(str(ICON_PNG))
        if icona is not None:
            app.setApplicationIconImage_(icona)

    _menu(appkit, app)

    rect = foundation.NSMakeRect(0, 0, 1280, 900)
    stile = 1 | 2 | 4 | 8  # titolo, chiudibile, minimizzabile, ridimensionabile
    finestra = appkit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, stile, 2, False
    )
    finestra.setTitle_("Open News")
    finestra.setReleasedWhenClosed_(False)

    config = webkit.WKWebViewConfiguration.alloc().init()
    web = webkit.WKWebView.alloc().initWithFrame_configuration_(rect, config)
    web.loadRequest_(
        foundation.NSURLRequest.requestWithURL_(foundation.NSURL.URLWithString_(url))
    )
    finestra.setContentView_(web)
    finestra.center()
    finestra.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)

    # Chiusa la finestra, l'app della finestra esce (il giornale resta acceso).
    foundation.NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
        "NSWindowWillCloseNotification", finestra, None, lambda _n: app.terminate_(None)
    )
    app.run()


if __name__ == "__main__":
    main()
