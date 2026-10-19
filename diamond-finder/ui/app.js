/* Diamond Finder page logic. Talks to Python through window.pywebview.api (see bridge.py). */
(() => {
  "use strict";
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (v, d = 1) => (Number.isInteger(v) ? String(v) : v.toFixed(d));
  const signed = (v) => (v > 0 ? "+" : v < 0 ? "−" : "") + num(Math.abs(Math.round(v * 10) / 10));

  // Label copy. Thresholds come from the presets the run used (state.result.rules), so edits there show here.
  const LABELS = {
    diamond: { name: "Diamond in the rough", tab: "Diamonds", accent: "#1f9bd1", accent2: "#0c2340",
      explain: (r) => `Numbers say star, scouts shrug: a stat score of ${r.labels.diamond.stat_min} or more, no older than his group's usual age, and the scouts rank his potential in the bottom ${r.labels.diamond.scout_max}%. These are your bargains.` },
    confirmed: { name: "Confirmed", tab: "Confirmed", accent: "#c41e3a", accent2: "#0c2340",
      explain: () => "The numbers and the scouts agree he's good. A safe pick, but every other club knows it too, so expect to pay full price." },
    trap: { name: "Overachiever trap", tab: "Traps", accent: "#d9822b", accent2: "#3a2a12",
      explain: () => "Great numbers, but he's older than his peers and the scouts aren't sold. Often a grown man beating up on kids, like a 23-year-old dominating an under-19 league." },
    raw: { name: "Raw tools", tab: "Raw tools", accent: "#7b5cd6", accent2: "#1d1640",
      explain: () => "Scouts love the potential, the stats aren't there yet. A project, like an FM wonderkid with five-star potential and two-star ability." },
    standout: { name: "Stat standout", tab: "Standouts", accent: "#1f9bd1", accent2: "#0c2340",
      explain: (r, res) => res.have_scout
        ? "Strong numbers, but no scout grade matched his name in your ratings file, so he can't be called a diamond or confirmed yet."
        : res.ratings_given
          ? "None of the names in your ratings file matched this stats export, so this is stats only: strong numbers at or below his group's usual age."
          : "No scout ratings loaded, so this is stats only: strong numbers at or below his group's usual age. Add the ratings export to split these into diamonds and confirmed players." },
    none: { name: "", tab: "Everyone", accent: "#4a5263", accent2: "#1a1d24",
      explain: (r) => `Every scored player, best diamond score first. No label usually means he just missed a cutoff (most often a stat score under ${r.labels.diamond.stat_min}), so low scout ranks near the top are still worth a look.` },
  };
  const PAGE = 60;

  const state = { files: { stats: null, ratings: null, out: null }, result: null, tab: "diamond", side: "all", shown: PAGE, update: null, installing: false };
  let api = null;

  // ------------------------------------------------------------- bridge
  function whenReady() {
    return new Promise((resolve) => {
      if (window.pywebview && window.pywebview.api) return resolve(window.pywebview.api);
      window.addEventListener("pywebviewready", () => resolve(window.pywebview.api), { once: true });
    });
  }
  async function call(name, ...args) {
    try { return await api[name](...args); }
    catch (e) { console.error(name, e); return { error: String((e && e.message) || e) }; }
  }

  // ------------------------------------------------------------- small UI helpers
  function toast(msg) {
    const t = document.createElement("span");
    t.className = "st-toast"; t.textContent = msg;
    $("#toastHost").append(t);
    setTimeout(() => t.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 400, fill: "forwards" }).finished.then(() => t.remove()), 2800);
  }
  const base = (p) => (p || "").split("/").filter(Boolean).pop() || p;
  const pretty = (p) => (p || "").replace(/^\/Users\/[^/]+/, "~");

  function showScreen(name) {
    $$(".screen").forEach((s) => (s.hidden = s.id !== name));
    $$(".st-top .st-tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.screen === name)));
    $("#main").scrollTop = 0;
  }

  // ------------------------------------------------------------- theme
  function applyTheme(t) {
    document.documentElement.dataset.theme = t === "light" ? "light" : "dark";
    $("#themeBtn").setAttribute("aria-label", t === "light" ? "Switch to dark" : "Switch to light");
  }
  $("#themeBtn").addEventListener("click", () => {
    const next = document.documentElement.dataset.theme === "light" ? "dark" : "light";
    applyTheme(next); call("set_pref", "theme", next);
  });

  // ------------------------------------------------------------- scout screen
  function paintFiles() {
    for (const kind of ["stats", "ratings", "out"]) {
      const row = $(`.file[data-kind="${kind}"]`);
      const small = $("small", row);
      const v = state.files[kind];
      row.classList.toggle("set", kind !== "out" && Boolean(v));
      small.textContent = v ? (kind === "out" ? pretty(v) : base(v)) : small.dataset.empty;
      small.title = v || "";
      const clear = $(".clear", row);
      if (clear) clear.hidden = !v;
      if (kind !== "out") $("[data-choose]", row).textContent = v ? "Change…" : "Choose…";
    }
    $("#runBtn").disabled = !state.files.stats;
  }
  $$("[data-choose]").forEach((b) => b.addEventListener("click", async () => {
    const kind = b.dataset.choose;
    const p = await call("choose", kind);
    if (typeof p === "string") { state.files[kind] = p; paintFiles(); hideError(); }
    else if (p && p.error) showError(p.error);
  }));
  $$("[data-clear]").forEach((b) => b.addEventListener("click", () => {
    const kind = b.dataset.clear;
    state.files[kind] = null; call("set_pref", kind, null); paintFiles();
  }));
  $("#presetsBtn").addEventListener("click", () => { call("edit_presets"); toast("Presets opened. Save the file, then run again"); });

  // Files dropped on the window arrive from Python (app.py) with their full path.
  window.dfDropped = (kind, path) => {
    state.files[kind] = path; paintFiles(); hideError(); showScreen("setup");
    toast(`${kind === "ratings" ? "Ratings" : "Stats"} file added: ${base(path)}`);
  };
  window.dfDropError = (msg) => { showScreen("setup"); showError(msg); };
  // Never let a drop navigate the window away from the app.
  ["dragover", "drop"].forEach((t) => document.addEventListener(t, (e) => e.preventDefault()));
  let dragDepth = 0;
  document.addEventListener("dragenter", () => { dragDepth++; document.body.classList.add("dragging"); });
  document.addEventListener("dragleave", () => { if (--dragDepth <= 0) { dragDepth = 0; document.body.classList.remove("dragging"); } });
  document.addEventListener("drop", () => { dragDepth = 0; document.body.classList.remove("dragging"); });

  function showError(msg) { const e = $("#setupError"); e.textContent = msg; e.hidden = false; }
  function hideError() { $("#setupError").hidden = true; }

  $("#runBtn").addEventListener("click", run);
  async function run() {
    hideError();
    $("#runBtn").disabled = true;
    $(".setup-panel").hidden = true;
    $("#running").hidden = false;
    const started = performance.now();
    const res = await call("run", state.files.stats, state.files.ratings, state.files.out);
    const wait = Math.max(0, 900 - (performance.now() - started)); // let the scan read as a moment, not a flicker
    await new Promise((r) => setTimeout(r, wait));
    $("#running").hidden = true;
    $(".setup-panel").hidden = false;
    paintFiles();
    if (!res || res.error) { showError(res ? res.error : "Something went wrong."); return; }
    state.result = res;
    state.tab = res.have_scout ? "diamond" : "standout";
    state.side = "all"; state.shown = PAGE;
    $('.st-top .st-tabs [data-screen="results"]').disabled = false;
    renderResults();
    showScreen("results");
    toast(`Saved to ${pretty(res.out_dir)}`);
  }

  // ------------------------------------------------------------- results
  function listFor(tab) {
    const r = state.result;
    let list = tab === "none" ? r.players : r.players.filter((p) => p.label_key === tab);
    if (tab === "raw") list = [...list].sort((a, b) => (b.scout ?? 0) - (a.scout ?? 0));
    if (state.side === "p") list = list.filter((p) => p.pitcher);
    if (state.side === "h") list = list.filter((p) => !p.pitcher);
    return list;
  }
  const countOf = (k) => { const c = state.result.counts[k] || { pitchers: 0, hitters: 0 }; return c.pitchers + c.hitters; };
  const tabsFor = (r) => (r.have_scout
    ? ["diamond", "confirmed", "trap", "raw", ...(countOf("standout") ? ["standout"] : []), "none"]
    : ["standout", "none"]);

  function renderResults() {
    const r = state.result;
    const rules = r.rules;
    renderHero();
    const lead = r.have_scout ? "diamond" : "standout";
    const skipped = r.skipped.pitchers + r.skipped.hitters;
    const pitchers = r.players.filter((p) => p.pitcher).length;
    $("#tiles").innerHTML = [
      [countOf(lead), LABELS[lead].name, "lead"],
      [r.players.length, `Players scored · ${pitchers} pitchers, ${r.players.length - pitchers} hitters`, ""],
      [skipped, `Skipped: under ${rules.min_sample.pitcher_ip} innings or ${rules.min_sample.hitter_pa} plate appearances`, ""],
    ].map(([n, label, cls]) => `<div class="${cls}" style="--tile-accent:${LABELS[lead].accent}"><b>${n}</b><small>${esc(label)}</small></div>`).join("");
    $("#labelTabs").innerHTML = tabsFor(r).map((k) =>
      `<button role="tab" data-tab="${k}" aria-selected="${k === state.tab}">${LABELS[k].tab}<span class="n">${k === "none" ? r.players.length : countOf(k)}</span></button>`).join("");
    $$("#labelTabs button").forEach((b) => b.addEventListener("click", () => { state.tab = b.dataset.tab; state.shown = PAGE; renderList(); }));
    // glossary: the stats this run used, then the scores, built from the presets in force
    $("#glossary").innerHTML = r.glossary.map((g) => `<dt>${esc(g.name)}</dt><dd>${esc(g.text)}</dd>`).join("");
    const pb = Object.entries(rules.position_bonus).filter(([, v]) => v).sort((a, b) => b[1] - a[1])
      .map(([k, v]) => `${k} ${signed(v)}`).join(", ");
    $("#scoreGlossary").innerHTML = [
      ["Diamond score", "Stat score plus the age, position, lefty and luck adjustments below. Lists are sorted by this."],
      ["Stat score", "0 to 100, where 50 is average for his own group (say, college starting pitchers). It is pulled toward 50 when he has played little, and nudged for how strong his competition was."],
      ["Age bonus", `${signed(rules.age.points_per_year)} for every year younger than his group's usual age, up to ${signed(rules.age.cap)}, and the same penalty for being older. Like an FM wonderkid doing it a season early.`],
      ["Position bonus", `Hitters only: ${pb || "none set"}. A good bat at a hard defensive position is rarer, like a centre-back who scores goals.`],
      ["Lefty bonus", `${signed(rules.lefty_pitcher_bonus)} for left-handed pitchers. Lefties are scarce and every club wants them, like a natural left-footed centre-back.`],
      ["Luck check", `Hitters only. BABIP is his batting average on balls he puts in play, and it swings a lot on luck. Far above his group's usual BABIP costs up to ${num(rules.luck_cap)} points; far below adds up to ${num(rules.luck_cap)}.`],
      ["Scout rank", "Where the game's scouts rank his potential against every other scored pitcher (or hitter) in your file, 0 to 100. It's a ranking, not OOTP's own potential rating. A high stat score with a low scout rank is what makes a diamond."],
    ].map(([t, d]) => `<dt>${esc(t)}</dt><dd>${esc(d)}</dd>`).join("");
    $("#notes").innerHTML = r.notes.map((n) => `<li>${esc(n)}</li>`).join("") || "<li>Nothing unusual. Every column was where it should be.</li>";
    $("#missing").innerHTML = r.missing.length
      ? `<span class="st-flag">Not found in your file: ${r.missing.map(esc).join(", ")}.</span>` : "";
    $("#mapping").innerHTML = r.mapping.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(v)}</td></tr>`).join("");
    renderList();
  }

  function heroPick() {
    const r = state.result;
    const lead = r.have_scout ? "diamond" : "standout";
    const top = r.players.find((p) => p.label_key === lead);
    return top ? { p: top, key: lead } : (r.players[0] ? { p: r.players[0], key: "none" } : null);
  }

  function renderHero() {
    const h = heroPick();
    const hero = $("#hero");
    if (!h) {
      hero.style.setProperty("--accent", "#4a5263"); hero.style.setProperty("--accent-2", "#1a1d24");
      $("#heroNum").textContent = "0";
      $("#heroMeta").innerHTML = `<span class="st-pill">No players scored</span>`;
      $("#heroName").textContent = "Nobody qualified";
      $("#heroLine").textContent = "Every player was under the minimum playing time. Lower it in presets, or export a fuller season.";
      $("#heroView").hidden = true;
      return;
    }
    const L = LABELS[h.key];
    hero.style.setProperty("--accent", L.accent); hero.style.setProperty("--accent-2", L.accent2);
    $("#heroNum").textContent = "1";
    const tag = h.key === "none" ? "Top of the board" : `No. 1 ${L.name.toLowerCase()}`;
    $("#heroMeta").innerHTML = `<span class="st-pill gold">${esc(tag)}</span><span>${esc(h.p.pos)} · ${esc(h.p.group)}${h.p.school ? " · " + esc(h.p.school) : ""}${h.p.age ? " · Age " + esc(h.p.age) : ""}</span>`;
    $("#heroName").textContent = h.p.name;
    $("#heroLine").textContent = h.key === "none"
      ? "No diamonds this time. This is the best diamond score on the board."
      : h.p.headline;
    $("#heroView").hidden = false;
    $("#heroView").onclick = () => openPlayer(h.p);
  }

  function rowHtml(p, i, animate) {
    const L = LABELS[state.tab === "none" ? p.label_key : state.tab];
    const delay = animate ? `animation-delay:${Math.min(i, 12) * 40}ms` : "animation:none";
    return `<button class="st-row" data-i="${i}" style="--accent:${L.accent};${delay}">
      <span class="st-row-num">${i + 1}</span>
      <span class="st-row-thumb">${esc(p.pos)}</span>
      <span><b>${esc(p.name)}</b><small class="meta">${esc(p.group)}${p.school ? " · " + esc(p.school) : ""}${p.age ? " · Age " + esc(p.age) : ""}${state.tab === "none" && p.label ? " · " + esc(LABELS[p.label_key].name) : ""}</small><small class="why">${esc(p.reasons[0] || "")}</small></span>
      <span class="cols">
        ${p.scout == null ? "" : `<span class="st-row-col wide muted">Scout rank<b>${p.scout}</b></span>`}
        <span class="st-row-col">Diamond<b>${p.diamond.toFixed(1)}</b></span>
      </span></button>`;
  }
  function bindRows(list, from) {
    $$("#rows .st-row").slice(from).forEach((b) => b.addEventListener("click", () => openPlayer(list[+b.dataset.i])));
  }
  function paintMore(list) {
    $("#moreBtn").hidden = list.length <= state.shown;
    $("#moreBtn").textContent = `Show more (${list.length - state.shown} left)`;
  }

  function renderList() {
    $$("#labelTabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === state.tab)));
    $$("#sideChips button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.side === state.side)));
    $("#labelExplain").textContent = LABELS[state.tab].explain(state.result.rules, state.result);
    const list = listFor(state.tab);
    const rows = $("#rows");
    if (!list.length) {
      const what = state.side === "p" ? "pitchers" : state.side === "h" ? "hitters" : "players";
      rows.innerHTML = `<div class="empty"><b>No ${what} here this time</b>That's normal for a small export. Try another tab, or loosen the cutoffs in presets.</div>`;
      $("#moreBtn").hidden = true;
      return;
    }
    rows.innerHTML = list.slice(0, state.shown).map((p, i) => rowHtml(p, i, true)).join("");
    bindRows(list, 0);
    paintMore(list);
  }
  $("#moreBtn").addEventListener("click", () => {
    const list = listFor(state.tab);
    const from = state.shown;
    state.shown += PAGE;
    $("#rows").insertAdjacentHTML("beforeend", list.slice(from, state.shown).map((p, j) => rowHtml(p, from + j, true)).join(""));
    bindRows(list, from);
    paintMore(list);
  });
  $$("#sideChips button").forEach((b) => b.addEventListener("click", () => { state.side = b.dataset.side; state.shown = PAGE; renderList(); }));

  $("#openReport").addEventListener("click", () => call("open", state.result.html_path));
  $("#openCsv").addEventListener("click", () => call("open", state.result.csv_path));
  $("#showFolder").addEventListener("click", () => call("open", state.result.csv_path, true));
  $("#newRun").addEventListener("click", () => showScreen("setup"));
  $$(".st-top .st-tabs button").forEach((b) => b.addEventListener("click", () => { if (!b.disabled) showScreen(b.dataset.screen); }));

  // ------------------------------------------------------------- sheets
  let returnFocus = null;
  function openSheet(html, cls = "") {
    closeSheet(true);
    returnFocus = document.activeElement;
    const host = $("#sheetHost");
    host.innerHTML = `<div class="st-scrim"></div><div class="st-sheet ${cls}" role="dialog" aria-modal="true">${html}</div>`;
    $(".app").inert = true;
    $(".st-scrim", host).addEventListener("click", () => closeSheet());
    $$("[data-close]", host).forEach((b) => b.addEventListener("click", () => closeSheet()));
    const first = $("[data-close]", host); if (first) first.focus();
    return $(".st-sheet", host);
  }
  function closeSheet(force) {
    if (state.installing && !force) return;
    const had = $("#sheetHost").innerHTML !== "";
    $("#sheetHost").innerHTML = "";
    $(".app").inert = false;
    if (had && returnFocus && document.contains(returnFocus)) returnFocus.focus();
  }
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeSheet(); });
  const closeBtn = `<button class="st-icon-btn" data-close aria-label="Close"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6L6 18"/></svg></button>`;

  function ledger(p) {
    const items = [
      ["Stat score", p.stat.toFixed(1), 0, "50 is average for his group"],
      ["Age", signed(p.age_bonus), p.age_bonus, p.median_age ? `his group's usual age is ${p.median_age}` : "no age to compare"],
      !p.pitcher && ["Position", signed(p.pos_bonus), p.pos_bonus, p.pos_bonus > 0 ? `${p.pos} is hard to fill` : p.pos_bonus < 0 ? `${p.pos} is easy to fill` : `${p.pos} gets no adjustment`],
      p.pitcher && ["Lefty", signed(p.lefty_bonus), p.lefty_bonus, p.hand === "L" ? "throws left-handed" : "throws right-handed"],
      !p.pitcher && ["Luck check", signed(p.luck_adj), p.luck_adj, p.luck_adj < 0 ? "BABIP above his group's: some luck" : p.luck_adj > 0 ? "BABIP below his group's: unlucky" : "BABIP close to normal"],
    ].filter(Boolean);
    return items.map(([k, v, raw, note]) =>
      `<span class="item ${raw > 0 ? "up" : raw < 0 ? "down" : ""}"><span>${esc(k)}<small>${esc(note)}</small></span><b>${esc(v)}</b></span>`).join("")
      + `<span class="item tot"><span>Diamond score</span><b>${p.diamond.toFixed(1)}</b></span>`;
  }

  function openPlayer(p) {
    const L = LABELS[p.label_key] || LABELS.none;
    const res = state.result;
    const meters = p.metrics.map((m) => m.pct == null
      ? `<div class="st-meter est"><span>${esc(m.name)}<span class="pct">no number</span></span><span class="t"></span><b>–</b></div>`
      : `<div class="st-meter"><span>${esc(m.name)}<span class="pct">better than ${m.pct}%</span></span><span class="t"><i style="width:${Math.max(3, m.pct)}%"></i></span><b>${esc(m.value)}</b></div>`).join("");
    const scoutCaption = res.have_scout ? "no ratings matched this name" : res.ratings_given ? "no names matched your ratings file" : "no ratings file loaded";
    const scoutMeter = p.scout == null
      ? `<div class="st-meter est"><span>Potential<span class="pct">${scoutCaption}</span></span><span class="t"></span><b>–</b></div>`
      : `<div class="st-meter thin"><span>Potential<span class="pct">above ${p.scout}% of them</span></span><span class="t"><i style="width:${Math.max(3, p.scout)}%"></i></span><b>${p.scout}</b></div>`;
    const facts = [
      ["Played", p.sample], p.comp && ["Competition", p.comp], p.cls && ["Class", p.cls],
      p.school && ["School", p.school],
    ].filter(Boolean).map(([k, v]) => `<span class="st-fact">${esc(k)} <b>${esc(v)}</b></span>`).join("");
    const hand = p.hand ? `<span class="st-pill">${p.pitcher ? "Throws" : "Bats"} ${esc({ L: "left", R: "right", S: "both sides" }[p.hand] || p.hand)}</span>` : "";
    const sheet = openSheet(`
      <span class="st-grab"></span>
      <div class="sheet-head"><span class="st-mark">${esc(p.pos)}</span>
        <div><h3>${esc(p.name)}</h3><p>${esc(p.group)}${p.age ? " · Age " + esc(p.age) : ""} · No. ${p.rank} overall</p></div>${closeBtn}</div>
      <div class="sheet-pills">${p.label ? `<span class="st-pill gold">${esc(p.label)}</span>` : ""}<span class="st-pill">${p.pitcher ? "Pitcher" : "Hitter"}</span>${hand}</div>
      <div class="sheet-cols">
        <div class="sheet-sec"><span class="st-label">How the diamond score adds up</span><div class="ledger">${ledger(p)}</div></div>
        <div class="sheet-sec"><span class="st-label">Against his group: ${esc(p.group)}</span><div class="st-meters">${meters}</div>
          <span class="st-label">Scouts' view, against every ${p.pitcher ? "pitcher" : "hitter"} in your file</span><div class="st-meters">${scoutMeter}</div></div>
      </div>
      <div class="sheet-sec"><span class="st-label">Why he's here</span><ul class="why-list">${p.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></div>
      <div class="facts">${facts}</div>`, "player");
    sheet.style.setProperty("--accent", L.accent);
  }

  // ------------------------------------------------------------- updates
  async function checkUpdate(manual) {
    const u = await call("check_update");
    if (!u || u.error) { if (manual) toast("Couldn't reach GitHub to check for updates"); return; }
    if (!u.available) { if (manual) toast(`You're on the latest version (${u.version})`); return; }
    state.update = u;
    const btn = $("#updateBtn");
    btn.classList.add("ready"); btn.textContent = `Update to ${u.version}`;
    if (manual) return openUpdate();
    const b = document.createElement("button");
    b.className = "st-banner";
    b.innerHTML = `<span class="st-mark"><svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M12 19V5M6 11l6-6 6 6"/></svg></span><span><b>Diamond Finder ${esc(u.version)} is ready</b><small>See what's new and install</small></span><span class="when">now</span>`;
    b.addEventListener("click", () => { b.remove(); openUpdate(); });
    $("#bannerHost").append(b);
    setTimeout(() => b.remove(), 12000);
  }
  function openUpdate() {
    const u = state.update; if (!u) return;
    $("#bannerHost").innerHTML = "";
    const sheet = openSheet(`
      <span class="st-grab"></span>
      <div class="sheet-head"><span class="st-mark">${esc(u.version)}</span><div><h3>Update ready</h3><p>You have ${esc($("#version").textContent)}. Your presets and results stay as they are.</p></div>${closeBtn}</div>
      ${u.notes ? `<div class="sheet-sec"><span class="st-label">What's new</span><p class="update-notes">${esc(u.notes)}</p></div>` : ""}
      <div class="st-actions" id="updActions"><button class="st-btn primary" id="installBtn">Install and restart</button><button class="st-btn glass" data-close>Later</button></div>
      <div class="installing" id="updRunning" hidden><span class="st-bar"><i></i></span><p>Downloading the new version. The app will close and reopen by itself.</p></div>
      <p class="st-flag" id="updError" hidden></p>`, "update");
    $("#installBtn", sheet).addEventListener("click", async () => {
      state.installing = true;
      sheet.classList.add("busy");
      $("#updateBtn").disabled = true;
      $("#updActions", sheet).hidden = true; $("#updRunning", sheet).hidden = false; $("#updError", sheet).hidden = true;
      const r = await call("install_update", u.url);
      if (r && r.error) {
        state.installing = false;
        sheet.classList.remove("busy");
        $("#updateBtn").disabled = false;
        $("#updRunning", sheet).hidden = true; $("#updActions", sheet).hidden = false;
        const e = $("#updError", sheet); e.textContent = r.error; e.hidden = false;
      }
    });
  }
  $("#updateBtn").addEventListener("click", () => (state.update ? openUpdate() : checkUpdate(true)));

  // ------------------------------------------------------------- start
  whenReady().then(async (a) => {
    api = a;
    const s = await call("state");
    applyTheme(s.theme);
    $("#version").textContent = "v" + s.version;
    state.files = { stats: s.stats || null, ratings: s.ratings || null, out: s.out || null };
    paintFiles();
    setTimeout(() => checkUpdate(false), 1500);
  });
})();
