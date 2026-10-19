"""Diamond Finder: the Mac window around diamond_finder.py."""
import html
import os
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import diamond_finder as df

APP = "Diamond Finder"
SUPPORT = os.path.expanduser(f"~/Library/Application Support/{APP}")
DEFAULT_OUT = os.path.expanduser(f"~/Documents/{APP}")


def bundled(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def presets_path():
    """Editable copy of presets.json, created on first launch."""
    os.makedirs(SUPPORT, exist_ok=True)
    p = os.path.join(SUPPORT, "presets.json")
    if not os.path.exists(p):
        shutil.copy(bundled("presets.json"), p)
    return p


def open_path(p):
    subprocess.call(["open", p] if sys.platform == "darwin" else ["xdg-open", p])


def md_to_html(md):
    """Small converter for the report's own Markdown (headings, tables, bullets, bold, code)."""
    def inline(s):
        s = html.escape(s)
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
        return re.sub(r"`(.+?)`", r"<code>\1</code>", s)
    out, in_table, in_list = [], False, False
    for line in md.splitlines():
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-"):
                continue
            if not in_table:
                out.append("<table><tr>" + "".join(f"<th>{inline(c)}</th>" for c in cells) + "</tr>")
                in_table = True
            else:
                out.append("<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells) + "</tr>")
            continue
        if in_table:
            out.append("</table>")
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
            out.append(f"<h{n}>{inline(m.group(2))}</h{n}>")
        elif line.strip():
            out.append(f"<p>{inline(line.rstrip())}</p>")
    if in_table:
        out.append("</table>")
    if in_list:
        out.append("</ul>")
    css = ("body{font:14px -apple-system,Helvetica,sans-serif;margin:24px;color:#222}"
           "table{border-collapse:collapse;margin:8px 0 20px;font-size:12px}"
           "th,td{border:1px solid #ccc;padding:4px 6px;vertical-align:top;text-align:left}"
           "th{background:#f0f0f0}h2{margin-top:32px;border-bottom:2px solid #c41e3a}"
           "@media(prefers-color-scheme:dark){body{background:#1e1e1e;color:#ddd}th{background:#333}"
           "th,td{border-color:#555}}")
    return f"<!doctype html><meta charset=utf-8><title>{APP} report</title><style>{css}</style>" + "\n".join(out)


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP)
        root.geometry("820x600")
        self.stats = tk.StringVar()
        self.ratings = tk.StringVar()
        self.out = tk.StringVar(value=DEFAULT_OUT)
        self.result = None

        f = ttk.Frame(root, padding=14)
        f.pack(fill="both", expand=True)
        f.columnconfigure(1, weight=1)
        rows = [("Stats CSV (required)", self.stats, self.pick_stats),
                ("Ratings CSV (optional)", self.ratings, self.pick_ratings),
                ("Save results to", self.out, self.pick_out)]
        for i, (lab, var, cmd) in enumerate(rows):
            ttk.Label(f, text=lab).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Entry(f, textvariable=var).grid(row=i, column=1, sticky="ew", padx=6)
            ttk.Button(f, text="Choose…", command=cmd).grid(row=i, column=2)

        b = ttk.Frame(f)
        b.grid(row=3, column=0, columnspan=3, sticky="w", pady=10)
        self.run_btn = ttk.Button(b, text="Find diamonds", command=self.run)
        self.run_btn.pack(side="left")
        self.report_btn = ttk.Button(b, text="Open report", command=self.open_report, state="disabled")
        self.report_btn.pack(side="left", padx=6)
        self.csv_btn = ttk.Button(b, text="Open CSV", command=self.open_csv, state="disabled")
        self.csv_btn.pack(side="left")
        ttk.Button(b, text="Edit presets", command=lambda: open_path(presets_path())).pack(side="left", padx=6)

        self.text = tk.Text(f, wrap="word", height=20, font=("Menlo", 12))
        self.text.grid(row=4, column=0, columnspan=3, sticky="nsew")
        f.rowconfigure(4, weight=1)
        self.say("Pick your OOTP stats export (Player Search or draft pool with a stats view), "
                 "optionally the ratings export, then press Find diamonds.\n\n"
                 f"Presets live in {presets_path()}. Press Edit presets to change cutoffs and weights.")

    def say(self, msg):
        self.text.delete("1.0", "end")
        self.text.insert("end", msg)

    def pick_stats(self):
        p = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All files", "*")])
        if p:
            self.stats.set(p)

    def pick_ratings(self):
        p = filedialog.askopenfilename(filetypes=[("CSV", "*.csv"), ("All files", "*")])
        if p:
            self.ratings.set(p)

    def pick_out(self):
        p = filedialog.askdirectory()
        if p:
            self.out.set(p)

    def run(self):
        if not os.path.isfile(self.stats.get()):
            messagebox.showerror(APP, "Choose a stats CSV first.")
            return
        self.run_btn.config(state="disabled")
        self.say("Working…")
        threading.Thread(target=self.work, daemon=True).start()

    def work(self):
        try:
            res = df.analyse(self.stats.get(), self.ratings.get().strip() or None,
                             df.load_presets(presets_path()), self.out.get())
            html_path = os.path.splitext(res["report_path"])[0] + ".html"
            with open(res["report_path"], encoding="utf-8") as f:
                md = f.read()
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(md_to_html(md))
            res["html_path"] = html_path
            msg = df.summary_text(res) + "\n\nNotes:\n" + "\n".join("- " + n for n in res["notes"]) + \
                f"\n\nSaved to {self.out.get()}"
            self.root.after(0, self.done, res, msg)
        except Exception as e:  # show any problem in the window
            self.root.after(0, self.done, None, f"Something went wrong:\n{e}")

    def done(self, res, msg):
        self.result = res
        self.say(msg)
        self.run_btn.config(state="normal")
        state = "normal" if res else "disabled"
        self.report_btn.config(state=state)
        self.csv_btn.config(state=state)

    def open_report(self):
        open_path(self.result["html_path"])

    def open_csv(self):
        open_path(self.result["csv_path"])


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
