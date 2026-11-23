# Letterboxd Stats Builder

Turn your Letterboxd data export into a clean, self-contained stats page: films watched, ratings, and your most-watched directors and actors.

> **Status: early shell.** The project structure, period logic, flag parsing, `.env` loading and the TMDB director and cast lookup are in place. Diary parsing, stats and page rendering are stubs marked `TODO`. See [Roadmap](#roadmap).

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
git clone https://github.com/<you>/letterboxd-stats-builder.git
cd letterboxd-stats-builder
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e .
```

Put the downloaded zip (or the extracted folder) in `data/`.

### Directors and actors (TMDB key)

Letterboxd's export does not include cast or crew. To rank directors and actors, the builder looks each film up on [The Movie Database (TMDB)](https://www.themoviedb.org), which is free for personal, non-commercial use.

1. Create a TMDB account and open **Settings → API** to request a key.
2. Copy either credential shown there: the **API Key** (32 hex characters) or the **API Read Access Token** (a long string starting `eyJ`). The builder detects which one you gave it.
3. Copy `.env.example` to `.env` and paste it in:

   ```
   TMDB_API_KEY=your-key-here
   ```

4. Check it works: `lsb --check-tmdb`

`.env` is git-ignored. Never commit your key or paste it into an issue. A real environment variable named `TMDB_API_KEY` takes priority over the file.

**How matching works:** each film is searched by title and release year. If nothing is found, the search is repeated without the year and accepts a release year within one year either side (Letterboxd and TMDB sometimes disagree). The title must match after ignoring case, accents and punctuation. Titles TMDB cannot match, such as TV episodes or very new films, are kept in your totals but left out of director and actor rankings, and are listed at the end of each run.

**Caching:** results, including misses, are saved to `.cache/tmdb.json`, so only new films are looked up on later runs and a fully cached run needs no key. Use `--refresh-cache` after fixing a mismatch or when new films gain credits.

Without a key you can run with `--no-enrich` and still get watch counts and ratings.

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
| `--no-enrich` | Skip the TMDB lookup | off |
| `--cast-limit N` | Top-billed cast members counted per film | `5` |
| `--refresh-cache` | Ignore cached TMDB results and look everything up again | off |
| `--check-tmdb` | Test your TMDB key with one lookup, then exit | off |

Output is plain HTML in `dist/`, with no external requests, so you can open it from disk or host it on GitHub Pages.

## Project layout

```
src/letterboxd_stats/
  cli.py        pipeline entry point
  config.py     flags and .env loading     (done, tested)
  periods.py    the five period windows    (done, tested)
  parse.py      read diary.csv             (stub)
  enrich.py     TMDB directors and cast    (done, tested)
  stats.py      build the stats dict       (stub)
  render.py     write HTML pages           (stub)
  templates/
    page.html   page template              (shell)
tests/
  test_periods.py
  test_config.py
  test_enrich.py
data/           put your Letterboxd export here (git-ignored)
```

Run the tests with `PYTHONPATH=src python -m unittest discover -s tests`.

## Roadmap

- [ ] `parse.py`: read the zip or folder, parse `diary.csv`
- [ ] Filter the diary to each period's date range
- [x] `enrich.py`: TMDB search, credits, local cache, report unmatched titles
- [x] Read `TMDB_API_KEY` from `.env`
- [ ] `stats.py`: totals, rating distribution, per-month counts, top directors and actors
- [ ] `render.py` and `page.html`: design the page, add a period switcher
- [ ] GitHub Actions workflow to publish to GitHub Pages

## Credits and attribution

This product uses the TMDB API but is not endorsed or certified by TMDB. This project is not affiliated with or endorsed by Letterboxd.

## Licence

[MIT](LICENSE) © Robert Lunt
