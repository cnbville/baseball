#!/usr/bin/env python3
"""Diamond Finder: spot OOTP amateur/pro players whose stats beat their scouting grades.

Standard library only. Usable from the command line or through app.py (the Mac window).

    python3 diamond_finder.py --stats stats.csv [--ratings ratings.csv] [--presets presets.json] [--out folder]
"""
import argparse
import csv
import io
import json
import os
import re
import statistics
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
LABEL_ORDER = ["Diamond in the rough", "Confirmed", "Overachiever trap", "Raw tools", "Stat standout"]

STAT_INFO = {
    # key: (display name, lower_is_better, format, plain-English meaning)
    "kbb_pct": ("K%-BB%", False, "{:.1f}",
                "strikeouts minus walks, as a share of batters faced. The single best quick read on a pitcher: "
                "he misses bats and doesn't give free passes. Think of it as an FM striker's xG minus misses."),
    "fip_minus": ("FIP-", True, "{:.0f}",
                  "Fielding Independent Pitching, scaled so 100 is average and lower is better (80 = 20% better "
                  "than average). It only counts what the pitcher controls: strikeouts, walks and home runs."),
    "fip": ("FIP", True, "{:.2f}",
            "Fielding Independent Pitching: an ERA-style number built only from strikeouts, walks and home runs, "
            "so bad defence behind him doesn't punish him. Lower is better."),
    "whip": ("WHIP", True, "{:.2f}",
             "Walks plus Hits per Inning Pitched: how many runners he lets on each inning. Lower is better; "
             "around 1.30 is ordinary, under 1.10 is very good."),
    "ops_plus": ("OPS+", False, "{:.0f}",
                 "On-base plus slugging, scaled so 100 is league average (130 = 30% better). The best all-round "
                 "single number for a hitter, like an FM average rating for strikers."),
    "ops": ("OPS", False, "{:.3f}",
            "On-base percentage plus slugging percentage: how often he reaches base plus how hard he hits. "
            ".700 is ordinary, .900+ is excellent."),
    "iso": ("ISO", False, "{:.3f}",
            "Isolated Power, slugging minus batting average: pure extra-base power (doubles, triples, home runs). "
            ".150 is decent, .250+ is big power."),
    "bb_pct": ("BB%", False, "{:.1f}%",
               "Walk rate, walks per plate appearance: plate discipline and pitch recognition. 10%+ is good."),
    "k_pct": ("K%", True, "{:.1f}%",
              "Strikeout rate, strikeouts per plate appearance. Lower is better; it shows contact skill. "
              "Under 15% is good, over 28% is a worry."),
}


# ----------------------------------------------------------------- helpers
def load_presets(path=None):
    path = path or os.path.join(HERE, "presets.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_csv_text(path):
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", errors="replace")


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "--", "NA", "N/A", "nan", "inf", "-inf"):
        return None
    s = s.rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def innings(v):
    """OOTP writes 86.1 for 86 1/3 innings and 86.2 for 86 2/3."""
    s = str(v or "").strip()
    if not s:
        return None
    m = re.fullmatch(r"(\d+)(?:\.(\d))?", s)
    if not m:
        return num(s)
    whole, frac = int(m.group(1)), int(m.group(2) or 0)
    return whole + (frac / 3.0 if frac in (1, 2) else frac / 10.0)


def norm_header(h):
    return re.sub(r"\s+", " ", (h or "").strip().lstrip("/").strip()).lower()


def name_key(name, suffixes):
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    tokens = [re.sub(r"[^a-z]", "", t) for t in re.split(r"[\s\-]+", s)]
    tokens = [t for t in tokens if t and t not in suffixes]
    return "".join(tokens)


def pct_ranks(values):
    """Percentile rank (0-100, mid-rank for ties) for each non-None value."""
    vals = [v for v in values if v is not None]
    n = len(vals)
    out = []
    for v in values:
        if v is None or n == 0:
            out.append(None)
            continue
        less = sum(1 for x in vals if x < v)
        eq = sum(1 for x in vals if x == v)
        out.append(100.0 * (less + 0.5 * eq) / n if n > 1 else 50.0)
    return out


def is_constant(values):
    vals = {round(v, 6) for v in values if v is not None}
    return len(vals) <= 1


def ordinal(n):
    n = int(round(n))
    suf = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


# ----------------------------------------------------------------- column mapping
class Columns:
    def __init__(self, header, aliases):
        self.header = header
        self.by_norm = {}
        for i, h in enumerate(header):
            self.by_norm.setdefault(norm_header(h), i)
        self.map = {}
        for key, names in aliases.items():
            for n in names:
                idx = self.by_norm.get(norm_header(n))
                if idx is not None:
                    self.map[key] = idx
                    break
        # pitching copies of duplicate names (K_1, BB_1, HR_1, G_1 ...)
        self.pitch_map = {}
        for key, idx in self.map.items():
            alt = self.by_norm.get(norm_header(header[idx]) + "_1")
            if alt is not None:
                self.pitch_map[key] = alt

    def get(self, row, key, pitcher=False):
        idx = self.pitch_map.get(key) if pitcher else None
        if idx is None:
            idx = self.map.get(key)
        if idx is None or idx >= len(row):
            return None
        return row[idx]

    def has(self, key):
        return key in self.map

    def describe(self, key):
        parts = []
        if key in self.map:
            parts.append(self.header[self.map[key]].strip())
        if key in self.pitch_map:
            parts.append(self.header[self.pitch_map[key]].strip() + " (pitchers)")
        return ", ".join(parts)


# ----------------------------------------------------------------- level / group
def level_of(hsc, lev):
    h = (hsc or "").strip().lower()
    if h:
        if "juco" in h or h.startswith("jc"):
            return "JuCo"
        if h.startswith("hs") or "high school" in h:
            return "HS"
        if h.startswith("co") or "college" in h:
            return "College"
        return hsc.strip()
    if lev and lev.strip():
        return lev.strip()
    return "All"


# ----------------------------------------------------------------- ratings
def load_ratings(path, presets, notes):
    text = read_csv_text(path)
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        notes.append("Ratings file was empty, so no scout grades were used.")
        return {}, {}
    first = rows[0][0].strip() if rows[0] else ""
    if not first.startswith("//"):
        notes.append("Ratings file header did not start with '//id, del, team_id' as expected; read it anyway.")
    header = [h.strip().lstrip("/").strip() for h in rows[0]]
    cols = Columns(header, presets["ratings_aliases"])
    missing = [k for k in presets["ratings_aliases"] if not cols.has(k)]
    found = {k: cols.describe(k) for k in presets["ratings_aliases"] if cols.has(k)}
    if "first" not in cols.map or "last" not in cols.map:
        notes.append("Ratings file has no FirstName/LastName columns, so scout grades could not be matched.")
        return {}, {"found": found, "missing": missing}

    suffixes = set(presets["name_suffixes_to_drop"])
    pcodes = {int(c) for c in presets["ratings_pitcher_position_codes"]}
    seen, out = {}, {}
    for r in rows[1:]:
        if not any(c.strip() for c in r):
            continue
        key = name_key(f"{cols.get(r, 'first') or ''} {cols.get(r, 'last') or ''}", suffixes)
        if not key:
            continue
        pos = num(cols.get(r, "position"))
        is_p = pos is not None and int(pos) in pcodes
        pots = {k: num(cols.get(r, k)) for k in list(presets["scout_weights"]["pitcher"]) +
                list(presets["scout_weights"]["hitter"])}
        seen[key] = seen.get(key, 0) + 1
        out[key] = {"is_pitcher": is_p, "pots": pots}
    dupes = [k for k, c in seen.items() if c > 1]
    for k in dupes:
        out.pop(k, None)
    if dupes:
        notes.append(f"{len(dupes)} name(s) appear more than once in the ratings file and were left unmatched.")
    return out, {"found": found, "missing": missing}


def scout_raw(entry, is_pitcher, presets):
    w = presets["scout_weights"]["pitcher" if is_pitcher else "hitter"]
    tot = wsum = 0.0
    for k, wt in w.items():
        v = entry["pots"].get(k)
        if v is not None:
            tot += v * wt
            wsum += wt
    return tot / wsum if wsum else None


# ----------------------------------------------------------------- main analysis
def analyse(stats_path, ratings_path=None, presets=None, out_dir=None, log=print):
    presets = presets or load_presets()
    notes = []
    text = read_csv_text(stats_path)
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    if len(rows) < 2:
        raise ValueError("The stats CSV has no player rows.")
    header = rows[0]
    cols = Columns(header, presets["column_aliases"])

    # --- report column mapping
    mapping = {k: cols.describe(k) for k in presets["column_aliases"] if cols.has(k)}
    missing = [k for k in presets["column_aliases"] if not cols.has(k)]
    for need in ("pos", "name"):
        if need not in cols.map:
            raise ValueError(f"Could not find a '{need}' column. Header was: {', '.join(h.strip() for h in header)}")

    pitch_set = {p.upper() for p in presets["pitcher_positions"]}
    players = []
    for r in rows[1:]:
        name = (cols.get(r, "name") or "").strip()
        if not name:
            continue
        pos = (cols.get(r, "pos") or "").strip().upper()
        is_p = pos in pitch_set
        level = level_of(cols.get(r, "hsc"), cols.get(r, "lev"))
        p = {
            "name": name, "pos": pos, "is_pitcher": is_p, "age": num(cols.get(r, "age")),
            "school": (cols.get(r, "school") or "").strip(), "class": (cols.get(r, "hsc") or "").strip(),
            "comp": (cols.get(r, "comp") or "").strip(), "level": level,
        }
        g = lambda k: num(cols.get(r, k, pitcher=is_p))
        if is_p:
            ip = innings(cols.get(r, "ip", pitcher=True))
            bf, k, bb = g("bf"), g("k"), g("bb")
            kbb = g("kbb_pct")
            if kbb is None and bf and k is not None and bb is not None:
                kbb = 100.0 * (k - bb) / bf
            role = pos if pos in ("SP", "RP") else None
            if role is None:
                gs, gg = g("gs"), g("g")
                role = "SP" if (gs is not None and gg and gs / gg >= 0.5) else "RP"
                if gs is None:
                    role = "SP" if (ip and gg and ip / gg >= 3.0) else "RP"
            p.update(sample=ip, sample_unit="IP", role=role, group=f"{level} {role}",
                     stats={"kbb_pct": kbb, "fip_minus": g("fip_minus"), "fip": g("fip"),
                            "whip": g("whip"), "era_plus": g("era_plus")})
        else:
            pa = g("pa")
            k, bb, avg, slg = g("k"), g("bb"), g("avg"), g("slg")
            p.update(sample=pa, sample_unit="PA", group=level,
                     stats={"ops_plus": g("ops_plus"), "ops": g("ops"),
                            "iso": (slg - avg) if slg is not None and avg is not None else None,
                            "bb_pct": 100.0 * bb / pa if pa and bb is not None else None,
                            "k_pct": 100.0 * k / pa if pa and k is not None else None})
        players.append(p)

    # --- KBB%: OOTP sometimes writes it as a fraction
    kb = [p["stats"]["kbb_pct"] for p in players if p["is_pitcher"] and p["stats"]["kbb_pct"] is not None]
    if kb and max(abs(v) for v in kb) <= 1.0 and cols.has("kbb_pct"):
        for p in players:
            if p["is_pitcher"] and p["stats"]["kbb_pct"] is not None:
                p["stats"]["kbb_pct"] *= 100.0
    if not cols.has("kbb_pct"):
        notes.append("No K%-BB% column, so it was calculated as (K - BB) / BF.")

    # --- minimum sample
    mins = presets["min_sample"]
    eligible, skipped = [], {"pitchers": 0, "hitters": 0}
    for p in players:
        need = mins["pitcher_ip"] if p["is_pitcher"] else mins["hitter_pa"]
        if p["sample"] is None or p["sample"] < need:
            skipped["pitchers" if p["is_pitcher"] else "hitters"] += 1
        else:
            eligible.append(p)
    pitchers = [p for p in eligible if p["is_pitcher"]]
    hitters = [p for p in eligible if not p["is_pitcher"]]

    # --- choose metrics (missing / constant fallbacks)
    pw = dict(presets["pitcher_weights"])
    hw = dict(presets["hitter_weights"])
    if pitchers:
        if is_constant([p["stats"]["era_plus"] for p in pitchers]) and cols.has("era_plus"):
            notes.append("ERA+ is the same for every pitcher (OOTP leaves it at 100 for amateurs), so it was ignored.")
        if "fip_minus" in pw and is_constant([p["stats"]["fip_minus"] for p in pitchers]):
            why = "missing" if not cols.has("fip_minus") else "the same for every pitcher"
            if not is_constant([p["stats"]["fip"] for p in pitchers]):
                pw["fip"] = pw.pop("fip_minus")
                notes.append(f"FIP- was {why}, so plain FIP was used in its place.")
            else:
                pw.pop("fip_minus")
                notes.append(f"FIP- was {why} and FIP was unusable too; its weight was spread over the other stats.")
        for key in list(pw):
            if is_constant([p["stats"][key] for p in pitchers]):
                pw.pop(key)
                notes.append(f"{STAT_INFO[key][0]} was missing or constant for pitchers and was dropped.")
    if hitters:
        if "ops_plus" in hw and is_constant([p["stats"]["ops_plus"] for p in hitters]):
            why = "missing" if not cols.has("ops_plus") else "the same for every hitter"
            hw["ops"] = hw.pop("ops_plus")
            notes.append(f"OPS+ was {why}, so plain OPS was used in its place.")
        for key in list(hw):
            if is_constant([p["stats"][key] for p in hitters]):
                hw.pop(key)
                notes.append(f"{STAT_INFO[key][0]} was missing or constant for hitters and was dropped.")

    # --- per-group scoring
    groups = {}
    for p in eligible:
        groups.setdefault(p["group"], []).append(p)
    comp_mult = {k.lower(): v for k, v in presets["competition_multipliers"].items()}
    agecfg = presets["age"]
    unknown_comp = set()
    small = []
    for gname, members in groups.items():
        if len(members) < presets.get("small_group_warning", 0):
            small.append(f"{gname} ({len(members)})")
        weights = pw if members[0]["is_pitcher"] else hw
        k_shrink = presets["shrink_k"]["pitcher_ip" if members[0]["is_pitcher"] else "hitter_pa"]
        for key in weights:
            lower = STAT_INFO[key][1]
            pr = pct_ranks([m["stats"][key] for m in members])
            for m, v in zip(members, pr):
                m.setdefault("pct", {})[key] = (100.0 - v) if (v is not None and lower) else v
        ages = [m["age"] for m in members if m["age"] is not None]
        med = statistics.median(ages) if ages else None
        for m in members:
            tot = wsum = 0.0
            for key, wt in weights.items():
                v = m["pct"].get(key)
                if v is not None:
                    tot += v * wt
                    wsum += wt
            raw = tot / wsum if wsum else 50.0
            n = m["sample"]
            score = 50 + (raw - 50) * n / (n + k_shrink)
            c = m["comp"].lower()
            mult = comp_mult.get(c)
            if mult is None:
                if c:
                    unknown_comp.add(m["comp"])
                mult = 1.0
            d = score - 50
            score = 50 + (d * mult if d > 0 else d / mult)
            m["raw"] = raw
            m["stat_score"] = score
            m["median_age"] = med
            if med is not None and m["age"] is not None:
                b = (med - m["age"]) * agecfg["points_per_year"]
                m["age_bonus"] = max(-agecfg["cap"], min(agecfg["cap"], b))
            else:
                m["age_bonus"] = 0.0
            m["diamond"] = score + m["age_bonus"]
            m["weights"] = weights
    if small:
        notes.append("Small groups, so percentiles there are rough: " + ", ".join(sorted(small)) + ".")
    if unknown_comp:
        notes.append("Unrecognised competition values treated as Average: " + ", ".join(sorted(unknown_comp)) + ".")
    if not cols.has("comp"):
        notes.append("No COMP column, so no competition adjustment was applied.")
    if not cols.has("hsc") and not cols.has("lev"):
        notes.append("No HSC or Lev/League column, so everyone was compared in one 'All' group.")

    # --- scout grades
    ratings_info = None
    have_scout = False
    if ratings_path:
        ratings, ratings_info = load_ratings(ratings_path, presets, notes)
        suffixes = set(presets["name_suffixes_to_drop"])
        keycount = {}
        for p in eligible:
            p["key"] = name_key(p["name"] if "," not in p["name"] else
                                " ".join(reversed([s.strip() for s in p["name"].split(",", 1)])), suffixes)
            keycount[p["key"]] = keycount.get(p["key"], 0) + 1
        matched = 0
        for p in eligible:
            e = ratings.get(p["key"]) if keycount[p["key"]] == 1 else None
            p["scout_raw"] = scout_raw(e, p["is_pitcher"], presets) if e else None
            matched += p["scout_raw"] is not None
        dup_stats = sum(1 for c in keycount.values() if c > 1)
        if dup_stats:
            notes.append(f"{dup_stats} name(s) appear more than once in the stats file and were left unmatched.")
        if presets.get("scout_percentile_pool", "matched") == "all":
            pools = {True: [], False: []}
            for e in ratings.values():
                v = scout_raw(e, e["is_pitcher"], presets)
                if v is not None:
                    pools[e["is_pitcher"]].append(v)
        else:
            pools = {True: [p["scout_raw"] for p in pitchers if p.get("scout_raw") is not None],
                     False: [p["scout_raw"] for p in hitters if p.get("scout_raw") is not None]}
        for p in eligible:
            v = p.get("scout_raw")
            pool = pools[p["is_pitcher"]]
            if v is None or not pool:
                p["scout"] = None
                continue
            less = sum(1 for x in pool if x < v)
            eq = sum(1 for x in pool if x == v)
            p["scout"] = 100.0 * (less + 0.5 * eq) / len(pool)
        have_scout = matched > 0
        notes.append(f"Scout grades matched for {matched} of {len(eligible)} scored players.")
        if ratings_info and ratings_info["missing"]:
            notes.append("Ratings columns not found: " + ", ".join(ratings_info["missing"]) + ".")
    else:
        for p in eligible:
            p["scout"] = None
        notes.append("No ratings file given, so players were labelled on stats alone ('Stat standout').")

    # --- labels
    L = presets["labels"]
    for p in eligible:
        s, a, sc = p["stat_score"], p["age_bonus"], p["scout"]
        lab = ""
        if sc is not None:
            if s >= L["diamond"]["stat_min"] and a >= L["diamond"]["age_bonus_min"] and sc <= L["diamond"]["scout_max"]:
                lab = "Diamond in the rough"
            elif s >= L["confirmed"]["stat_min"] and sc >= L["confirmed"]["scout_min"]:
                lab = "Confirmed"
            elif s >= L["trap"]["stat_min"] and a <= L["trap"]["age_bonus_max"] and sc <= L["trap"]["scout_max"]:
                lab = "Overachiever trap"
            elif sc >= L["raw_tools"]["scout_min"] and s <= L["raw_tools"]["stat_max"]:
                lab = "Raw tools"
        elif s >= L["stat_standout"]["stat_min"] and a >= L["stat_standout"]["age_bonus_min"]:
            lab = "Stat standout"
        p["label"] = lab
        p["reasons"] = reasons(p)

    eligible.sort(key=lambda p: -p["diamond"])
    for i, p in enumerate(eligible, 1):
        p["rank"] = i

    result = {
        "players": eligible, "skipped": skipped, "notes": notes, "mapping": mapping, "missing": missing,
        "ratings_info": ratings_info, "have_scout": have_scout, "pitcher_weights": pw, "hitter_weights": hw,
        "total_rows": len(players), "presets": presets,
    }
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
        result["csv_path"] = write_csv(eligible, os.path.join(out_dir, "diamond_finder_results.csv"))
        result["report_path"] = write_report(result, os.path.join(out_dir, "diamond_finder_report.md"),
                                             stats_path, ratings_path)
    return result


def reasons(p):
    out = []
    ranked = sorted(((v, k) for k, v in p.get("pct", {}).items() if v is not None and k in p["weights"]),
                    reverse=True)[:2]
    for v, k in ranked:
        disp, _, fmt, _ = STAT_INFO[k]
        val = p["stats"][k]
        top = max(1, int(round(100 - v)))
        out.append(f"{disp} {fmt.format(val)}, top {top}% of {p['group']}")
    if p["age"] is not None and p["median_age"] is not None:
        diff = p["median_age"] - p["age"]
        if abs(diff) < 0.05:
            out.append(f"same age as {p['group']} median ({p['median_age']:g})")
        else:
            word = "younger" if diff > 0 else "older"
            out.append(f"{abs(diff):g} yr {word} than {p['group']} median ({p['median_age']:g})")
    if p["comp"].lower() in ("poor", "fair"):
        out.append(f"{p['comp']} competition, stats discounted")
    if p.get("scout") is not None:
        out.append(f"scout {ordinal(p['scout'])} pct")
    elif "scout" in p:
        out.append("no scout grade")
    return "; ".join(out)


def fmt_sample(p):
    if p["sample_unit"] == "IP":
        whole = int(p["sample"])
        thirds = int(round((p["sample"] - whole) * 3))
        return f"{whole}.{thirds} IP" if thirds else f"{whole} IP"
    return f"{int(p['sample'])} PA"


def write_csv(players, path):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Rank", "Label", "Name", "POS", "Age", "Group", "School", "Class", "Comp", "Sample",
                    "DiamondScore", "StatScore", "AgeBonus", "ScoutPct", "Reasons"])
        for p in players:
            w.writerow([p["rank"], p["label"], p["name"], p["pos"],
                        "" if p["age"] is None else f"{p['age']:g}", p["group"], p["school"], p["class"],
                        p["comp"], fmt_sample(p), f"{p['diamond']:.1f}", f"{p['stat_score']:.1f}",
                        f"{p['age_bonus']:+.1f}", "" if p["scout"] is None else f"{p['scout']:.0f}",
                        p["reasons"]])
    return path


def label_counts(players):
    c = {l: {"pitchers": 0, "hitters": 0} for l in LABEL_ORDER}
    for p in players:
        if p["label"]:
            c[p["label"]]["pitchers" if p["is_pitcher"] else "hitters"] += 1
    return c


def write_report(res, path, stats_path, ratings_path):
    P = res["players"]
    top_n = res["presets"].get("report_top_n", 25)
    lines = ["# Diamond Finder report", "",
             f"Stats file: `{os.path.basename(stats_path)}`" +
             (f"  \nRatings file: `{os.path.basename(ratings_path)}`" if ratings_path else "  \nRatings file: none"),
             "", f"Rows read: {res['total_rows']}. Scored: {len(P)}. "
             f"Skipped for small samples: {res['skipped']['pitchers']} pitchers "
             f"(under {res['presets']['min_sample']['pitcher_ip']} IP) and {res['skipped']['hitters']} hitters "
             f"(under {res['presets']['min_sample']['hitter_pa']} PA).", ""]
    counts = label_counts(P)
    lines += ["## How many in each label", "", "| Label | Pitchers | Hitters |", "|---|---|---|"]
    for l in LABEL_ORDER:
        if counts[l]["pitchers"] or counts[l]["hitters"] or l != "Stat standout" or not res["have_scout"]:
            lines.append(f"| {l} | {counts[l]['pitchers']} | {counts[l]['hitters']} |")
    lines.append("")
    for l in LABEL_ORDER:
        sel = [p for p in P if p["label"] == l]
        if not sel:
            continue
        if l == "Raw tools":
            sel.sort(key=lambda p: -(p["scout"] or 0))
        lines += [f"## {l}", ""]
        for side, is_p in (("Pitchers", True), ("Hitters", False)):
            part = [p for p in sel if p["is_pitcher"] == is_p][:top_n]
            if not part:
                continue
            lines += [f"### {side}", "",
                      "| # | Name | POS | Age | Group | School | Comp | Sample | Diamond | Stat | Age+ | Scout | Reasons |",
                      "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
            for p in part:
                lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {:.1f} | {:.1f} | {:+.0f} | {} | {} |".format(
                    p["rank"], p["name"], p["pos"], "" if p["age"] is None else f"{p['age']:g}", p["group"],
                    p["school"], p["comp"], fmt_sample(p), p["diamond"], p["stat_score"], p["age_bonus"],
                    "" if p["scout"] is None else f"{p['scout']:.0f}", p["reasons"].replace("|", "/")))
            lines.append("")
    lines += ["## Column mapping", "", "| Needed | Found in your file |", "|---|---|"]
    for k, v in res["mapping"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "Not found: " + (", ".join(res["missing"]) or "none") + ".", ""]
    lines += ["## Notes and workarounds", ""] + [f"- {n}" for n in res["notes"]] + [""]
    lines += ["## Stats used, in plain words", ""]
    for k in list(res["pitcher_weights"]) + list(res["hitter_weights"]):
        lines.append(f"- **{STAT_INFO[k][0]}**: {STAT_INFO[k][3]}")
    lines += ["", "**Stat score** is 0-100 with 50 = average for the player's own group, shrunk toward 50 when the "
              "sample is small and adjusted for the level of competition. **Age bonus** rewards players younger "
              "than their group's typical age (like an FM wonderkid doing it a year early). **Scout** is where the "
              "game's scouts rank his potential among the other scored players, 0-100.", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def summary_text(res, top=5):
    P = res["players"]
    c = label_counts(P)
    out = [f"Scored {len(P)} players; skipped {res['skipped']['pitchers']} pitchers and "
           f"{res['skipped']['hitters']} hitters with too small a sample."]
    for l in LABEL_ORDER:
        n = c[l]["pitchers"] + c[l]["hitters"]
        if n or l != "Stat standout":
            out.append(f"  {l}: {n} ({c[l]['pitchers']} P, {c[l]['hitters']} H)")
    lead = "Diamond in the rough" if res["have_scout"] else "Stat standout"
    best = [p for p in P if p["label"] == lead][:top]
    out.append(f"\nTop {len(best)} {lead.lower()}:")
    for p in best:
        out.append(f"  {p['rank']}. {p['name']} ({p['pos']}, {p['group']}, {p['school']}) "
                   f"diamond {p['diamond']:.1f}: {p['reasons']}")
    if res["missing"]:
        out.append("\nColumns not found: " + ", ".join(res["missing"]))
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stats", required=True)
    ap.add_argument("--ratings")
    ap.add_argument("--presets")
    ap.add_argument("--out", default="diamond_finder_output")
    a = ap.parse_args(argv)
    res = analyse(a.stats, a.ratings, load_presets(a.presets), a.out)
    print(summary_text(res))
    print(f"\nCSV: {res['csv_path']}\nReport: {res['report_path']}")


if __name__ == "__main__":
    sys.exit(main())
