# LetterRobd

A Letterboxd stat builder, written in Python using Letterboxd's export data. It turns your export into a clean, self-contained stats page: films watched, ratings, and your most-watched directors and actors.

> **Status: early shell.** The project structure, period logic, flag parsing, `.env` loading and the director and cast lookup are in place. Diary parsing, stats and page rendering are stubs marked `TODO`. See [Roadmap](#roadmap).

## Report periods

| Period | Flag value | Covers |
| --- | --- | --- |
| Past month | `month` | Rolling 1 month ending today |
| Past 3 months | `3months` | Rolling 3 months ending today |
| Past 6 months | `6months` | Rolling 6 months ending today |
| Past year | `year` | Rolling 12 months ending today |
| Calendar year | `calendar-year` | 1 Jan to 31 Dec of a chosen year (defaults to the current year) |

Periods are based on the **Watched Date** in your diary, not the day you logged the entry.

## 1. Get your data out of Letterboxd

Letterboxd lets you download everything you have logged as a zip of CSV files.

1. Log in to [letterboxd.com](https://letterboxd.com) in a web browser. The export is on the website rather than in the mobile app.
2. Open **Settings**: click your avatar in the top right, then **Settings**.
3. Go to the **Data** tab (direct link: <https://letterboxd.com/settings/data/>).
4. Click **Export Your Data**.
5. Your browser downloads a zip named like `letterboxd-<username>-<date>.zip`.

The zip contains, among other files:

| File | What it holds |
| --- | --- |
| `diary.csv` | Every diary entry: name, year, rating, rewatch flag, tags, logged date and **Watched Date**. **This is the file the builder uses.** |
| `ratings.csv` | Your ratings, one row per film |
| `watched.csv` | Every film you have marked as watched |
| `reviews.csv`, `likes/`, `lists/`, `watchlist.csv` | Not used yet |

Menu labels on Letterboxd can change. If you cannot find the option, look for "Export" under your account settings.

**Privacy:** the export is your personal data. The included `.gitignore` keeps everything in `data/` and any `.zip` out of git, so you will not publish it by accident. Do not commit your export to a public repository.

## 2. Set up

You need [Python](https://www.python.org) 3.10 or newer. The project uses only the standard library, so there is nothing else to install.

```bash
git clone https://github.com/roblunt11/LetterRobd.git
cd LetterRobd
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

Put the downloaded zip (or the extracted folder) in `data/`. That is all the setup there is: no account, no API key.

### Directors and actors

Letterboxd's export does not include cast or crew, so the builder looks each film up in an open database. Choose one with `--source`:

| Source | Sign-up | Notes |
| --- | --- | --- |
| `wikidata` (default) | **None** | Free, open data. Only film titles and years are sent. Directors are reliable; cast is patchier (see below). |
| `tmdb` | Free account and API key | Most complete cast data. Add `TMDB_API_KEY` to `.env`. |

Check your chosen source works with one lookup: `lsb --check-source`

**Wikidata, what to expect.**
- Each film takes about three polite requests, one at a time, as Wikimedia asks, so a diary of a few hundred films takes a few minutes the first time.
- Wikidata does not guarantee billing order for cast. Where editors recorded an order it is used; otherwise the stored order is, which is often but not always the billing order. Treat actor rankings as approximate. Directors are the strong suit.
- Coverage varies. Very new or obscure films may have no cast, or no director, listed. TV episodes and many specials are not film items, so they will not match.
- Wikimedia asks apps to identify themselves. The builder sends its name and your optional `LSB_CONTACT` (an email address or URL, set in `.env`) in the User-Agent. Without it, the project URL is sent. If Wikimedia ever answers 403, setting `LSB_CONTACT` is the fix.

**Matching.** Films are matched by title and release year. Wikidata matches the English label or alias, trying common spelling variants (curly apostrophes, "and" for "&", hyphen for en dash), and accepts a release year within one year either side, because Letterboxd and Wikidata sometimes disagree. Titles that cannot be matched are kept in your totals but left out of director and actor rankings, and each run lists them. Films that match but have no credits are listed separately.

**Caching.** Results, including misses, are saved per source in `.cache/<source>.json`, so only new films are looked up on later runs, and a fully cached run needs no network. Use `--refresh-cache` after fixing a mismatch or when films gain credits.

**TMDB option.** Create a free account at [themoviedb.org](https://www.themoviedb.org), request a key under **Settings → API**, and copy `.env.example` to `.env` with either the **API Key** or the **API Read Access Token** as `TMDB_API_KEY`. `.env` is git-ignored; never commit your key.

Without any lookup you can run with `--no-enrich` and still get watch counts and ratings.

## 3. Build

```bash
lsb --period all
# or, without installing:  PYTHONPATH=src python -m letterboxd_stats --period all
```

| Flag | Meaning | Default |
| --- | --- | --- |
| `--input PATH` | Export zip or extracted folder | `./data` |
| `--out DIR` | Output folder | `./dist` |
| `--period NAME` | `month`, `3months`, `6months`, `year`, `calendar-year` or `all` | `all` |
| `--calendar-year YYYY` | Year for `calendar-year` | current year |
| `--as-of YYYY-MM-DD` | Treat this date as "today" for rolling periods | today |
| `--source NAME` | Credits source: `wikidata` or `tmdb` | `wikidata` |
| `--no-enrich` | Skip the director and cast lookup | off |
| `--cast-limit N` | Top-billed cast members counted per film | `5` |
| `--refresh-cache` | Ignore cached results and look everything up again | off |
| `--check-source` | Test the chosen source with one lookup, then exit | off |

Output is plain HTML in `dist/`, with no external requests, so you can open it from disk or host it on GitHub Pages.

## Project layout

```
src/letterboxd_stats/
  cli.py        pipeline entry point
  config.py     flags and .env loading     (done, tested)
  periods.py    the five period windows    (done, tested)
  parse.py      read diary.csv             (stub)
  enrich.py     source-agnostic lookup + cache   (done, tested)
  wikidata.py   Wikidata credits source    (done, tested offline)
  tmdb.py       TMDB credits source        (done, tested offline)
  sources.py    choose a source            (done, tested)
  http.py       shared HTTP transport
  stats.py      build the stats dict       (stub)
  render.py     write HTML pages           (stub)
  templates/
    page.html   page template              (shell)
tests/          unit tests, no network needed
data/           put your Letterboxd export here (git-ignored)
```

Run the tests with `PYTHONPATH=src python -m unittest discover -s tests`.

## Roadmap

- [ ] `parse.py`: read the zip or folder, parse `diary.csv`
- [ ] Filter the diary to each period's date range
- [x] Credits lookup with local cache and reporting of unmatched titles (Wikidata, TMDB)
- [x] Read settings from `.env`
- [ ] Try the Wikidata lookup against a real diary and tune the matching
- [ ] `stats.py`: totals, rating distribution, per-month counts, top directors and actors
- [ ] `render.py` and `page.html`: design the page, add a period switcher
- [ ] GitHub Actions workflow to publish to GitHub Pages
- [x] Set `PROJECT_URL` in `__init__.py` to the real repository URL

## Credits and attribution

Director and cast data comes from [Wikidata](https://www.wikidata.org) (CC0) or, if you choose it, from TMDB. If you use TMDB: this product uses the TMDB API but is not endorsed or certified by TMDB. This project is not affiliated with or endorsed by Letterboxd or Wikimedia.

## Licence

[MIT](LICENSE) © Robert Lunt
