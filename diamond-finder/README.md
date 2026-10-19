# Diamond Finder

Finds OOTP 27 "diamonds in the rough": players whose stats are strong for their age and level but whose scouting grades are lukewarm.

- `diamond_finder.py`: the analysis (standard library only). Command line: `python3 diamond_finder.py --stats stats.csv --ratings ratings.csv --out results`
- `app.py`: the Mac window. Built into `DiamondFinder.dmg` by `.github/workflows/build-mac.yml`, published on the `diamond-finder` release.
- `presets.json`: every cutoff and weight. The app copies it to `~/Library/Application Support/Diamond Finder/presets.json` on first launch; edit that copy.

Outputs: `diamond_finder_results.csv` (every scored player), `diamond_finder_report.md` and `.html` (top 25 per label).
