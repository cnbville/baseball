"""Diamond Finder: the Mac window. The page lives in ui/, the Python side in bridge.py."""
import json
import os

import webview
from webview.dom import DOMEventHandler

from bridge import APP, Api, bundled

GROUND = {"dark": (7, 8, 11), "light": (245, 245, 247)}  # Showtime --ground, so the title bar melts into the page


def style_titlebar(window, theme):
    """Hide the native title text and paint the title bar in the page's own colour."""
    try:
        import AppKit
        from PyObjCTools import AppHelper
    except ImportError:  # not on a Mac
        return

    def apply():
        w = window.native
        if w is None:
            return
        dark = theme != "light"
        r, g, b = GROUND["dark" if dark else "light"]
        colour = AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(r / 255, g / 255, b / 255, 1.0)
        w.setTitlebarAppearsTransparent_(True)
        w.setTitleVisibility_(AppKit.NSWindowTitleHidden)
        w.setAppearance_(AppKit.NSAppearance.appearanceNamed_(
            AppKit.NSAppearanceNameDarkAqua if dark else AppKit.NSAppearanceNameAqua))
        w.setBackgroundColor_(colour)
        try:  # pywebview paints the title bar container itself; repaint it to match
            w.contentView().superview().subviews().lastObject().setBackgroundColor_(colour)
        except Exception:
            pass

    AppHelper.callAfter(apply)


def sniff_kind(path):
    """A ratings export starts with '//id, del, team_id'; anything else is treated as stats."""
    try:
        with open(path, "rb") as f:
            head = f.read(64).decode("utf-8-sig", "ignore").lstrip()
    except OSError:
        return None
    return "ratings" if head.startswith("//") else "stats"


def main():
    api = Api()
    theme = api.state()["theme"]
    url = bundled("ui", "index.html") + ("#light" if theme == "light" else "")
    window = webview.create_window(
        APP, url=url, js_api=api, width=1200, height=820, min_size=(900, 640),
        background_color="#f5f5f7" if theme == "light" else "#07080b",
    )
    api._window = window
    api._on_theme = lambda t: style_titlebar(window, t)

    def on_drop(event):
        files = [f.get("pywebviewFullPath") for f in event.get("dataTransfer", {}).get("files", [])]
        csvs = [p for p in files if p and p.lower().endswith((".csv", ".txt"))]
        if not csvs:
            window.evaluate_js(f"window.dfDropError({json.dumps('Drop a CSV export from OOTP (a file ending in .csv).')})")
            return
        for path in csvs[:2]:
            kind = sniff_kind(path)
            if kind:
                api.set_pref(kind, path)
                window.evaluate_js(f"window.dfDropped({json.dumps(kind)}, {json.dumps(path)})")

    hooked = []

    def on_loaded():
        style_titlebar(window, api.state()["theme"])
        if hooked:
            return
        hooked.append(True)
        doc = window.dom.document
        doc.events.dragover += DOMEventHandler(lambda e: None, True, True)
        doc.events.drop += DOMEventHandler(on_drop, True, True)

    window.events.loaded += on_loaded
    webview.start(http_server=True, debug=bool(os.environ.get("DF_DEBUG")))


if __name__ == "__main__":
    main()
