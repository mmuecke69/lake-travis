# Lake Travis level dashboard

Public, no-sign-in dashboard of the Lake Travis reservoir level at Mansfield Dam (Point Venture, TX).

**Live page:** https://mmuecke69.github.io/lake-travis/

A GitHub Actions workflow runs `update.py` and `build_site.py` about every 15 minutes, then updates `data.json` (and `index.html` if the shell changed) when the published reading or LCRA operations note actually changed. GitHub Pages is served from this `main` branch root (`index.html`, `data.json`, `.nojekyll`).

The aired.sh sandbox at https://aired.sh/p/0uX2i9tNOK loads this same live `data.json` in the browser (with an inlined fallback if that fetch fails).

All numbers and the LCRA note come from published LCRA or TWDB sources. Nothing is invented.
