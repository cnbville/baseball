"""Self-update from the GitHub releases of cnbville/baseball."""
import json
import os
import re
import shlex
import ssl
import subprocess
import sys
import tempfile
import urllib.request

from version import __version__

REPO = "cnbville/baseball"
ASSET = "DiamondFinder.dmg"
API = f"https://api.github.com/repos/{REPO}/releases/latest"


def _ctx():
    # The bundled Python may lack macOS root certificates; fall back to the system bundle.
    for cafile in ("/etc/ssl/cert.pem",):
        if os.path.exists(cafile):
            return ssl.create_default_context(cafile=cafile)
    return ssl.create_default_context()


def _ver(s):
    s = s.lstrip("vV").split("-v")[-1].lstrip("vV")
    out = []
    for part in s.split("."):
        m = re.match(r"\d+", part)  # "0-rc1" -> 0, so a pre-release never sorts above its final release
        out.append(int(m.group()) if m else 0)
    return tuple(out)


def check():
    """Return (version, dmg_url, notes) if GitHub has a newer release, else None."""
    req = urllib.request.Request(API, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "DiamondFinder"})
    with urllib.request.urlopen(req, timeout=10, context=_ctx()) as r:
        rel = json.load(r)
    tag = rel.get("tag_name", "")
    if _ver(tag) <= _ver(__version__):
        return None
    for a in rel.get("assets", []):
        if a.get("name") == ASSET:
            return tag.split("-v")[-1].lstrip("v"), a["browser_download_url"], rel.get("body") or ""
    return None


def current_app_path():
    """Path of the running .app bundle, or None when not running as a bundled app."""
    if not getattr(sys, "frozen", False):
        return None
    p = os.path.abspath(sys.executable)
    while p != "/" and not p.endswith(".app"):
        p = os.path.dirname(p)
    return p if p.endswith(".app") else None


def install(url, progress=lambda msg: None):
    """Download the dmg, then hand off to a helper that swaps the app once we quit and relaunches it."""
    app = current_app_path()
    if not app:
        raise RuntimeError("Updates only work from the installed app.")
    if app.startswith("/Volumes/"):
        raise RuntimeError("Drag Diamond Finder into your Applications folder first, then update from there.")
    if not os.access(os.path.dirname(app), os.W_OK):
        raise RuntimeError("Your Mac account isn't allowed to replace apps in that folder. "
                           "Download the new version from GitHub and drag it into Applications instead.")
    work = tempfile.mkdtemp(prefix="dfupdate")
    dmg = os.path.join(work, ASSET)
    progress("Downloading update…")
    req = urllib.request.Request(url, headers={"User-Agent": "DiamondFinder"})
    with urllib.request.urlopen(req, timeout=120, context=_ctx()) as r, open(dmg, "wb") as f:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            f.write(chunk)
    progress("Installing update…")
    script = os.path.join(work, "swap.sh")
    with open(script, "w") as f:
        f.write(f"""#!/bin/bash
# Swap in the new app once Diamond Finder has quit. The old copy is only removed after the new one is fully in place.
APP={shlex.quote(app)}
WORK={shlex.quote(work)}
mkdir -p "$HOME/Library/Logs"
exec >>"$HOME/Library/Logs/Diamond Finder update.log" 2>&1
echo "--- $(date) updating $APP"
while kill -0 {os.getpid()} 2>/dev/null; do sleep 0.5; done
MNT=$(mktemp -d)
if hdiutil attach -nobrowse -quiet -mountpoint "$MNT" "$WORK/{ASSET}"; then
  NEW="$MNT/Diamond Finder.app"
  rm -rf "$APP.new" "$APP.old"
  if [ -d "$NEW" ] && ditto "$NEW" "$APP.new"; then
    if mv "$APP" "$APP.old" && mv "$APP.new" "$APP"; then
      rm -rf "$APP.old"
      xattr -dr com.apple.quarantine "$APP" || true
      echo "updated"
    else
      [ -d "$APP" ] || mv "$APP.old" "$APP"
      echo "swap failed, kept the old version"
    fi
  else
    echo "copy failed, kept the old version"
  fi
  rm -rf "$APP.new"
  hdiutil detach -quiet "$MNT" || true
else
  echo "could not open the downloaded dmg"
fi
open "$APP"
rm -rf "$WORK"
""")
    os.chmod(script, 0o755)
    subprocess.Popen(["/bin/bash", script], start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
