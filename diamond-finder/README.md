# Diamond Finder

Finds OOTP 27 "diamonds in the rough": players whose stats are strong for their age and level but whose scouting grades are lukewarm.

- `diamond_finder.py`: the analysis (standard library only). Command line: `python3 diamond_finder.py --stats stats.csv --ratings ratings.csv --out results`
- `app.py`: the Mac window. Built into `DiamondFinder.dmg` by `.github/workflows/build-mac.yml`, published as a `diamond-finder-v<version>` GitHub release. Latest download: https://github.com/cnbville/baseball/releases/latest/download/DiamondFinder.dmg
- `presets.json`: every cutoff and weight. The app copies it to `~/Library/Application Support/Diamond Finder/presets.json` on first launch; edit that copy.

Outputs: `diamond_finder_results.csv` (every scored player), `diamond_finder_report.md` and `.html` (top 25 per label).

## Updates

The app checks GitHub's latest release on launch (and via **Check for updates**). If its tag is newer than `version.py`, it offers to download the dmg, swap the app in place and reopen. To ship an update: bump `__version__` in `version.py`, commit with a one-line summary (that becomes the release notes) and push.
