"""The window's Python side: file pickers, running the analysis, settings and updates.

Kept free of any GUI import so it can be tested headless; app.py hands it the window.
"""
import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import threading

import diamond_finder as df
import updater
from version import __version__

APP = "Diamond Finder"
SUPPORT = os.path.expanduser(f"~/Library/Application Support/{APP}")
DEFAULT_OUT = os.path.expanduser(f"~/Documents/{APP}")
LABEL_KEYS = {
    "Diamond in the rough": "diamond", "Confirmed": "confirmed", "Overachiever trap": "trap",
    "Raw tools": "raw", "Stat standout": "standout", "": "none",
}


def bundled(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


# Settings a person is likely to have tuned by hand; these survive a presets upgrade.
KEEP_ON_UPGRADE = ("min_sample", "shrink_k", "competition_multipliers", "age", "labels", "scout_weights",
                   "scout_percentile_pool", "report_top_n", "small_group_warning", "name_suffixes_to_drop")
_upgrade_note = []


def presets_path():
    """Editable copy of presets.json, created on first launch and upgraded when the app ships a newer one."""
    os.makedirs(SUPPORT, exist_ok=True)
    p = os.path.join(SUPPORT, "presets.json")
    if not os.path.exists(p):
        shutil.copy(bundled("presets.json"), p)
        return p
    with open(bundled("presets.json"), encoding="utf-8") as f:
        new = json.load(f)
    try:
        with open(p, encoding="utf-8") as f:
            old = json.load(f)
    except (OSError, ValueError):
        old = None
    if old is None or old.get("presets_version", 1) < new.get("presets_version", 1):
        backup = os.path.join(SUPPORT, f"presets.v{(old or {}).get('presets_version', 1)}.backup.json")
        shutil.copy(p, backup)
        merged = dict(new)
        for k in KEEP_ON_UPGRADE:
            if old and isinstance(old.get(k), type(new.get(k))):
                merged[k] = old[k]
        with open(p, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        _upgrade_note.append("Presets were upgraded for this version: new stats, position, lefty and luck settings were "
                             "added, and your sample sizes, label cutoffs and other tweaks were kept. The old file "
                             f"was saved as {os.path.basename(backup)}.")
    return p


def open_path(p, reveal=False):
    if sys.platform == "darwin":
        subprocess.call(["open", "-R", p] if reveal else ["open", p])
    else:
        subprocess.call(["xdg-open", os.path.dirname(p) if reveal else p])


# ----------------------------------------------------------------- result -> JSON for the page
COLUMN_NAMES = {
    "pos": "position (POS)", "name": "player name", "age": "age", "school": "school", "comp": "competition (COMP)",
    "hsc": "class (HSC)", "lev": "level or league", "pa": "plate appearances (PA)", "ab": "at bats (AB)",
    "h": "hits (H)", "hr": "home runs (HR)", "bb": "walks (BB)", "k": "strikeouts (K)", "avg": "batting average (AVG)",
    "obp": "on-base percentage (OBP)", "slg": "slugging (SLG)", "ops": "OPS", "ops_plus": "OPS+",
    "ip": "innings pitched (IP)", "bf": "batters faced (BF)", "g": "games (G)", "gs": "games started (GS)",
    "era": "ERA", "era_plus": "ERA+", "fip": "FIP", "fip_minus": "FIP-", "whip": "WHIP", "k9": "K/9", "bb9": "BB/9",
    "kbb_pct": "K%-BB%", "woba": "wOBA", "iso_col": "ISO", "bb_pct_col": "walk rate (BB%)",
    "k_pct_col": "strikeout rate (K%)", "sb": "stolen bases (SB)", "babip": "BABIP", "siera": "SIERA",
    "hr9": "HR/9", "bats": "bats (B)", "throws": "throws (T)",
}
# Plain-English "better than X% of ..." phrases for the hero line
PHRASES = {
    "woba": "creates runs better than", "ops_plus": "hits better than", "ops": "hits better than",
    "iso": "hits for more power than", "bb_pct": "draws more walks than", "k_pct": "strikes out less than",
    "sb_rate": "steals more bases than", "kbb_pct": "has a better strikeout-to-walk edge than",
    "fip_minus": "prevents runs better than", "fip": "prevents runs better than",
    "siera": "has a better skill-based ERA than", "p_k_pct": "strikes out more batters than",
    "whip": "lets fewer runners on than", "hr9": "gives up fewer home runs than",
}


def group_plain(group, pitcher):
    level, _, role = group.partition(" ")
    lvl = {"HS": "high school", "College": "college", "JuCo": "junior college"}.get(level, level)
    who = {"SP": "starting pitchers", "RP": "relief pitchers"}.get(role, "pitchers" if pitcher else "hitters")
    return f"{lvl} {who}" if lvl != "All" else who


def headline(p):
    ranked = sorted(((v, k) for k, v in p.get("pct", {}).items() if v is not None and k in p["weights"]),
                    reverse=True)[:2]
    if not ranked:
        return ""
    parts = [f"{PHRASES.get(k, 'beats')} {min(99, int(v))}%" for v, k in ranked]
    line = " and ".join(parts) + f" of {group_plain(p['group'], p['is_pitcher'])}."
    line = line[0].upper() + line[1:]
    if p.get("age") is not None and p.get("median_age") is not None and p["median_age"] - p["age"] >= 1:
        yrs = p["median_age"] - p["age"]
        line += f" And he's {yrs:g} year{'s' if yrs != 1 else ''} younger than most of them."
    return line


def player_json(p):
    metrics = []
    for key in p.get("weights", {}):
        disp, lower, fmt, _ = df.STAT_INFO[key]
        val, pct = p["stats"].get(key), p.get("pct", {}).get(key)
        metrics.append({"key": key, "name": disp, "value": None if val is None else fmt.format(val),
                        "pct": None if pct is None else round(pct), "lower_better": lower})
    return {
        "rank": p["rank"], "label": p["label"], "label_key": LABEL_KEYS.get(p["label"], "none"),
        "name": p["name"], "pos": p["pos"], "pitcher": p["is_pitcher"],
        "age": None if p["age"] is None else f"{p['age']:g}",
        "median_age": None if p.get("median_age") is None else f"{p['median_age']:g}",
        "group": p["group"], "school": p["school"], "cls": p["class"], "comp": p["comp"],
        "sample": df.fmt_sample(p), "diamond": round(p["diamond"], 1), "stat": round(p["stat_score"], 1),
        "age_bonus": round(p["age_bonus"], 1), "pos_bonus": round(p.get("pos_bonus", 0), 1),
        "lefty_bonus": round(p.get("lefty_bonus", 0), 1), "luck_adj": round(p.get("luck_adj", 0), 1),
        "hand": p.get("throws") if p["is_pitcher"] else p.get("bats"),
        "scout": None if p["scout"] is None else round(p["scout"]),
        "reasons": [r for r in p["reasons"].split("; ") if r], "metrics": metrics, "headline": headline(p),
    }


def result_json(res, ratings_given=False):
    counts = df.label_counts(res["players"])
    used = list(dict.fromkeys(list(res["pitcher_weights"]) + list(res["hitter_weights"])))
    pr = res["presets"]
    return {
        "players": [player_json(p) for p in res["players"]],
        "counts": {LABEL_KEYS[k]: v for k, v in counts.items()},
        "skipped": res["skipped"], "total_rows": res["total_rows"], "notes": res["notes"],
        "mapping": [[COLUMN_NAMES.get(k, k), v] for k, v in res["mapping"].items()],
        "missing": [COLUMN_NAMES.get(k, k) for k in res["missing"]],
        "have_scout": res["have_scout"], "ratings_given": bool(ratings_given),
        "glossary": [{"name": df.STAT_INFO[k][0] + (
            (" (pitchers)" if k in res["pitcher_weights"] else " (hitters)")
            if sum(df.STAT_INFO[j][0] == df.STAT_INFO[k][0] for j in used) > 1 else ""),
            "text": df.STAT_INFO[k][3]} for k in used],
        "csv_path": res.get("csv_path"), "report_path": res.get("report_path"),
        "html_path": res.get("html_path"), "out_dir": os.path.dirname(res.get("csv_path") or ""),
        "rules": {"min_sample": pr["min_sample"], "labels": pr["labels"], "age": pr["age"],
                  "position_bonus": pr.get("position_bonus", {}), "lefty_pitcher_bonus": pr.get("lefty_pitcher_bonus", 0),
                  "luck_cap": pr.get("luck", {}).get("cap", 0)},
    }


# ----------------------------------------------------------------- Showtime-styled HTML report
TEXT_COLS = {"Label", "Name", "POS", "Group", "School", "Comp", "Sample", "Reasons", "Needed", "Found in your file"}


def md_to_html(md, theme="dark"):
    """Turn the report's own Markdown (headings, tables, bullets, bold, code) into a Showtime page."""
    def inline(s):
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    out, in_table, in_list, kinds = [], False, False, []
    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            if not in_table:
                kinds = [("r" if c == "Reasons" else "t") if c in TEXT_COLS else "" for c in cells]
                out.append('<div class="st-table dense"><table><thead><tr>' +
                           "".join(f'<th class="{k}">{inline(c)}</th>' for c, k in zip(cells, kinds)) +
                           "</tr></thead><tbody>")
                in_table = True
            else:
                out.append("<tr>" + "".join(f'<td class="{k}">{inline(c)}</td>'
                                            for c, k in zip(cells, kinds + [""] * len(cells))) + "</tr>")
            continue
        if in_table:
            out.append("</tbody></table></div>")
            in_table = False
        if line.startswith("- "):
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{inline(line[2:])}</li>")
            continue
        if in_list:
            out.append("</ul>")
            in_list = False
        m = re.match(r"(#+) (.*)", line)
        if m:
            n = len(m.group(1))
            cls = ' class="st-wide"' if n == 1 else ""
            out.append(f"<h{n}{cls}>{inline(m.group(2))}</h{n}>")
        elif line.strip():
            out.append(f"<p>{inline(line.rstrip())}</p>")
    if in_table:
        out.append("</tbody></table></div>")
    if in_list:
        out.append("</ul>")
    css = open(bundled("ui", "showtime.css"), encoding="utf-8").read()
    font = ""
    fp = bundled("ui", "fonts", "archivo-latin.woff2")
    if os.path.exists(fp):
        b64 = base64.b64encode(open(fp, "rb").read()).decode()
        font = ("@font-face{font-family:'Archivo';font-style:normal;font-weight:400 900;font-stretch:62% 125%;"
                f"src:url(data:font/woff2;base64,{b64}) format('woff2')}}")
    page = ("body{margin:0}main{max-width:1200px;margin:0 auto;padding:40px var(--gutter) 80px}"
            "h1{font-size:44px;line-height:1;margin-bottom:12px!important}"
            "h2{font-size:26px;margin:44px 0 6px!important}h3{margin:22px 0 4px!important}"
            "h3{font-size:11px;font-weight:700;letter-spacing:.14em;text-transform:uppercase;color:var(--fg3)}"
            "p{color:var(--fg2);max-width:80ch;margin:6px 0!important}ul{color:var(--fg2);max-width:90ch}"
            "li{margin:6px 0}code{font-size:13px;color:var(--fg)}b{color:var(--fg)}"
            ".st-table{margin:8px 0}.st-table .t,.st-table .r{text-align:left}"
            ".st-table td.r{white-space:normal;min-width:340px}")
    theme_attr = ' data-theme="light"' if theme == "light" else ""
    return (f"<!doctype html><html{theme_attr}><head><meta charset=utf-8>"
            "<meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{APP} report</title><style>{font}{css}{page}</style></head>"
            "<body class=st><main>" + "\n".join(out) + "</main></body></html>")


# ----------------------------------------------------------------- the API the page calls
class Api:
    """Every public method is callable from the page as window.pywebview.api.<name>()."""

    def __init__(self):
        self._window = None
        self._on_theme = None  # set by app.py to recolour the native title bar
        self._installing = threading.Lock()
        self._settings_file = os.path.join(SUPPORT, "settings.json")

    # settings -----------------------------------------------------------
    def _load(self):
        try:
            with open(self._settings_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def _save(self, s):
        os.makedirs(SUPPORT, exist_ok=True)
        with open(self._settings_file, "w", encoding="utf-8") as f:
            json.dump(s, f, indent=1)

    def state(self):
        s = self._load()
        for k in ("stats", "ratings"):
            if s.get(k) and not os.path.isfile(s[k]):
                s[k] = None
        return {"version": __version__, "stats": s.get("stats"), "ratings": s.get("ratings"),
                "out": s.get("out") or DEFAULT_OUT, "theme": s.get("theme", "dark"),
                "presets": presets_path()}

    def set_pref(self, key, value):
        if key not in ("stats", "ratings", "out", "theme"):
            return False
        s = self._load()
        s[key] = value
        self._save(s)
        if key == "theme" and self._on_theme:
            self._on_theme(value)
        return True

    # files --------------------------------------------------------------
    def choose(self, kind):
        """Show a native picker. kind: stats, ratings or out. Returns the chosen path or None."""
        import webview  # only inside the app
        if kind == "out":
            r = self._window.create_file_dialog(webview.FOLDER_DIALOG, directory=self.state()["out"])
        else:
            r = self._window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("CSV files (*.csv)", "All files (*.*)"))
        if not r:
            return None
        path = r[0] if isinstance(r, (list, tuple)) else r
        self.set_pref(kind, path)
        return path

    def open(self, path, reveal=False):
        if path and os.path.exists(path):
            open_path(path, reveal)
            return True
        return False

    def edit_presets(self):
        open_path(presets_path())
        return True

    # analysis -----------------------------------------------------------
    def run(self, stats, ratings=None, out=None):
        try:
            if not stats or not os.path.isfile(stats):
                return {"error": "Choose a stats CSV first."}
            if ratings and not os.path.isfile(ratings):
                return {"error": f"Can't find the ratings file anymore:\n{ratings}"}
            out = out or DEFAULT_OUT
            res = df.analyse(stats, ratings or None, df.load_presets(presets_path()), out)
            res["notes"] = _upgrade_note + res["notes"]
            _upgrade_note.clear()
            html_path = os.path.splitext(res["report_path"])[0] + ".html"
            with open(res["report_path"], encoding="utf-8") as f:
                md = f.read()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(md_to_html(md, self._load().get("theme", "dark")))
            res["html_path"] = html_path
            return result_json(res, ratings_given=bool(ratings))
        except Exception as e:  # shown on the page
            return {"error": str(e)}

    # updates ------------------------------------------------------------
    def check_update(self):
        try:
            info = updater.check()
        except Exception as e:
            return {"error": str(e)}
        if not info:
            return {"available": False, "version": __version__}
        version, url, notes = info
        return {"available": True, "version": version, "url": url, "notes": notes.strip()}

    def install_update(self, url):
        if not self._installing.acquire(blocking=False):
            return {"error": "An update is already being installed."}
        try:
            updater.install(url)
        except Exception as e:
            self._installing.release()
            return {"error": str(e)}
        # give the page a moment to show "Restarting…", then quit so the helper can swap the app
        threading.Timer(0.8, self._quit).start()
        return {"ok": True}

    def _quit(self):
        if self._window is not None:
            self._window.destroy()
