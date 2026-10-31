"""
Weekly Music Drop
=================
Pulls this week's new album releases from Wikipedia's actively-updated
"List of <year> albums" page, and publishes the result to a GitHub Pages
site. No API key, no billing, no account needed for the data source itself.

Designed to run as a GitHub Actions scheduled workflow (see
.github/workflows/weekly-update.yml) — GitHub supplies GITHUB_TOKEN and
GITHUB_REPOSITORY automatically there, no secrets file needed.

Can also be run anywhere else (e.g. PythonAnywhere) with a local
secrets_config.py file (see secrets_config.py.example) — that file is never
committed to git.
"""

import base64
import datetime
import json
import os
import re
import sys
import urllib.parse

import requests
from bs4 import BeautifulSoup

try:
    import secrets_config as cfg
except ImportError:
    # No local secrets file — assume we're running in GitHub Actions, which
    # provides these as environment variables instead.
    class _EnvConfig:
        GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
        GITHUB_REPO = os.environ.get("GITHUB_REPO") or os.environ.get("GITHUB_REPOSITORY")
        GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

    cfg = _EnvConfig()
    if not cfg.GITHUB_TOKEN or not cfg.GITHUB_REPO:
        raise RuntimeError(
            "No secrets_config.py found, and GITHUB_TOKEN / GITHUB_REPO "
            "environment variables aren't set either. Nothing to authenticate with."
        )

GITHUB_API = "https://api.github.com"
WIKI_USER_AGENT = "weekly-music-drop/1.0 (personal hobby project; contact via GitHub)"

SITE_TITLE = "Weekly Music Drop"


# ---------------------------------------------------------------------------
# 1. Pull this week's albums from Wikipedia's "List of <year> albums" page
# ---------------------------------------------------------------------------

def parse_wiki_date(text, year):
    text = re.sub(r"\[.*?\]", "", text).strip()
    for fmt in ("%B %d, %Y", "%B %d", "%d %B %Y", "%d %B"):
        try:
            dt = datetime.datetime.strptime(text, fmt)
            if "%Y" not in fmt:
                dt = dt.replace(year=year)
            return dt.date()
        except ValueError:
            continue
    return None


def parse_wiki_albums_table(table, year):
    """Pull (date, artist, title) rows out of one Wikipedia albums table.

    Each month's table is preceded by a one-cell "Go to: January | February
    | ..." navigation row that lives inside the same <table> — so the real
    header row (with "Release date", "Artist", etc.) isn't always row zero.
    This scans the first few rows to find it instead of assuming.

    Also handles the common case where Wikipedia doesn't repeat the release
    date for multiple albums that came out on the same day (so some rows
    have one fewer cell than the header row).
    """
    rows = table.find_all("tr")
    if not rows:
        return []

    def find_col(headers, names):
        for i, h in enumerate(headers):
            for n in names:
                if n in h:
                    return i
        return None

    header_row_idx = None
    date_idx = artist_idx = title_idx = None
    for idx, row in enumerate(rows[:5]):
        headers = [c.get_text(strip=True).lower() for c in row.find_all(["th", "td"])]
        d = find_col(headers, ["release date", "date"])
        a = find_col(headers, ["artist"])
        t = find_col(headers, ["album", "title"])
        if d is not None and a is not None and t is not None:
            header_row_idx, date_idx, artist_idx, title_idx = idx, d, a, t
            break
    if header_row_idx is None:
        return []
    total_cols = len(rows[header_row_idx].find_all(["th", "td"]))

    results = []
    current_date_text = None
    for row in rows[header_row_idx + 1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        texts = [c.get_text(" ", strip=True) for c in cells]
        if len(texts) == total_cols:
            current_date_text = texts[date_idx]
            artist_text, title_text = texts[artist_idx], texts[title_idx]
        elif len(texts) == total_cols - 1 and date_idx == 0:
            # Date cell was omitted because it's the same as the row above.
            artist_text, title_text = texts[artist_idx - 1], texts[title_idx - 1]
        else:
            continue

        if not (current_date_text and artist_text and title_text):
            continue
        release_date = parse_wiki_date(current_date_text, year)
        if release_date:
            results.append((release_date, artist_text, title_text))
    return results


def wikipedia_page_titles(year, months):
    """Wikipedia page title(s) to read for the given months of a year.

    Once a year gets busy, Wikipedia splits "List of <year> albums" into
    "(January–June)" and "(July–December)" pages and leaves the plain page
    as a short stub with no albums on it. That's what silently broke the
    site in October 2026.
    """
    halves = {"January\u2013June" if m <= 6 else "July\u2013December" for m in months}
    return [f"List_of_{year}_albums_({h})" for h in sorted(halves)]


def read_wikipedia_page(page_title, year):
    """Return every (date, artist, title) row found on one Wikipedia page."""
    url = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(page_title, safe="()_")
    resp = requests.get(url, headers={"User-Agent": WIKI_USER_AGENT}, timeout=60)
    if resp.status_code == 404:
        print(f"  {page_title}: page not found")
        return []
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []
    for table in soup.find_all("table"):
        rows.extend(parse_wiki_albums_table(table, year))
    print(f"  {page_title}: read {len(rows)} album rows")
    return rows


def fetch_wikipedia_albums(week_start, week_end):
    """Fetch real album releases in [week_start, week_end] from Wikipedia.

    Wikipedia maintains actively-updated "List of <year> albums" pages —
    free, no account or key needed, and limited to albums Wikipedia
    considers independently notable, which naturally filters out noise.

    Raises an error (instead of quietly returning nothing) if a page
    contains no album rows at all, since that means Wikipedia's layout has
    changed again and "no albums this week" would be a false answer.
    """
    all_rows = []
    for year in sorted({week_start.year, week_end.year}):  # a week can span New Year's
        months = {d.month for d in (week_start, week_end) if d.year == year}

        year_rows = []
        for page_title in wikipedia_page_titles(year, months):
            year_rows.extend(read_wikipedia_page(page_title, year))

        if not year_rows:
            # Year isn't split into halves (or the naming changed) — try the plain page.
            year_rows = read_wikipedia_page(f"List_of_{year}_albums", year)

        if not year_rows:
            raise RuntimeError(
                f"Read Wikipedia's {year} album list but found no album rows on it at all. "
                f"The page layout or naming has probably changed — not publishing an empty week."
            )
        all_rows.extend(year_rows)

    albums = [
        {"artist": artist, "title": title}
        for release_date, artist, title in all_rows
        if week_start <= release_date <= week_end
    ]

    # De-duplicate while preserving order (the same album can appear in more
    # than one table on some pages).
    seen = set()
    unique_albums = []
    for a in albums:
        key = (a["artist"].lower(), a["title"].lower())
        if key not in seen:
            seen.add(key)
            unique_albums.append(a)
    return unique_albums


# ---------------------------------------------------------------------------
# 2. GitHub Contents API helpers (no git/SSH needed)
# ---------------------------------------------------------------------------

def github_get_file(path):
    """Return (content_str, sha) for a file in the repo, or (None, None) if missing."""
    url = f"{GITHUB_API}/repos/{cfg.GITHUB_REPO}/contents/{path}"
    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {cfg.GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
        params={"ref": cfg.GITHUB_BRANCH},
        timeout=30,
    )
    if resp.status_code == 404:
        return None, None
    resp.raise_for_status()
    data = resp.json()
    return base64.b64decode(data["content"]).decode("utf-8"), data["sha"]


def github_put_file(path, content_str, message, sha=None):
    url = f"{GITHUB_API}/repos/{cfg.GITHUB_REPO}/contents/{path}"
    body = {
        "message": message,
        "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
        "branch": cfg.GITHUB_BRANCH,
    }
    if sha:
        body["sha"] = sha
    resp = requests.put(
        url,
        headers={"Authorization": f"Bearer {cfg.GITHUB_TOKEN}", "Accept": "application/vnd.github+json"},
        json=body,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def github_upsert_file(path, content_str, message):
    """Create or update a file, fetching its sha first if it already exists."""
    _, sha = github_get_file(path)
    github_put_file(path, content_str, message, sha=sha)


# ---------------------------------------------------------------------------
# 3. HTML rendering
# ---------------------------------------------------------------------------

def esc(s):
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render_release_lists(week):
    albums = week.get("albums", [])

    html = ""
    if albums:
        html += '<h3>Albums</h3>\n<ul class="releases">\n'
        for a in albums:
            html += f'  <li><span class="artist">{esc(a["artist"])}</span> &ndash; {esc(a["title"])}</li>\n'
        html += "</ul>\n"
    else:
        html += "<p><em>No notable album releases found this week.</em></p>\n"

    return html


PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{page_title}</title>
<meta name="description" content="{description}">
<link rel="stylesheet" href="{css_path}style.css">
</head>
<body>
<header>
  <a class="site-title" href="{root_path}index.html">{site_title}</a>
  <p class="tagline">New albums, every Friday.</p>
</header>
<main>
{body}
</main>
<footer>
  <p><a href="{root_path}archive/index.html">Browse all past weeks</a></p>
</footer>
</body>
</html>
"""


def render_week_page(week, root_path="../"):
    body = f'<h2>{esc(week["label"])}</h2>\n' + render_release_lists(week)
    return PAGE_TEMPLATE.format(
        page_title=f'{week["label"]} \u2014 {SITE_TITLE}',
        description=f'Albums released the week of {week["label"]}.',
        css_path=root_path,
        root_path=root_path,
        site_title=SITE_TITLE,
        body=body,
    )


def render_index(weeks):
    if not weeks:
        body = "<p>Check back Friday for the first drop.</p>"
    else:
        latest = weeks[0]
        body = f'<h2>{esc(latest["label"])}</h2>\n' + render_release_lists(latest)
        if len(weeks) > 1:
            body += '<h3 class="past-heading">Past weeks</h3>\n<ul class="archive-list">\n'
            for w in weeks[1:9]:
                body += f'  <li><a href="archive/{w["date"]}.html">{esc(w["label"])}</a></li>\n'
            body += "</ul>\n"
            if len(weeks) > 9:
                body += '<p><a href="archive/index.html">See all past weeks &rarr;</a></p>\n'

    return PAGE_TEMPLATE.format(
        page_title=SITE_TITLE,
        description="What albums came out this week, sourced from Wikipedia automatically every Friday.",
        css_path="",
        root_path="",
        site_title=SITE_TITLE,
        body=body,
    )


def render_archive_index(weeks):
    body = "<h2>All past weeks</h2>\n<ul class=\"archive-list\">\n"
    for w in weeks:
        body += f'  <li><a href="{w["date"]}.html">{esc(w["label"])}</a></li>\n'
    body += "</ul>\n"
    return PAGE_TEMPLATE.format(
        page_title=f"Archive \u2014 {SITE_TITLE}",
        description="Every past week of new album releases.",
        css_path="../",
        root_path="../",
        site_title=SITE_TITLE,
        body=body,
    )


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------

def requested_week_end():
    """A specific Friday to (re)build, if one was asked for — otherwise None.

    Set via the WEEK_END environment variable (the GitHub "Run workflow"
    box passes it in) or a `--date YYYY-MM-DD` argument. Used to repair a
    past week that came out wrong.
    """
    value = os.environ.get("WEEK_END", "").strip()
    if "--date" in sys.argv:
        value = sys.argv[sys.argv.index("--date") + 1]
    return datetime.date.fromisoformat(value) if value else None


def main():
    today = datetime.date.today()
    override = requested_week_end()

    # When run somewhere that can only schedule daily (e.g. free PythonAnywhere),
    # skip every day except Friday. GitHub Actions already fires only on Fridays,
    # and a specific date or --force always runs.
    if (not override and "--force" not in sys.argv
            and not os.environ.get("GITHUB_ACTIONS") and today.weekday() != 4):
        print(f"Today ({today}) isn't Friday — skipping. Run with --force to publish anyway.")
        return

    # "This week" = the 7 days ending on the chosen Friday (normally today).
    week_end = override or today
    week_start = week_end - datetime.timedelta(days=6)
    label = f"Week of {week_start:%B %-d}\u2013{week_end:%-d, %Y}" if week_start.month == week_end.month \
        else f"Week of {week_start:%B %-d} \u2013 {week_end:%B %-d, %Y}"

    print(f"Checking Wikipedia for albums released {week_start} to {week_end}...")
    albums = fetch_wikipedia_albums(week_start, week_end)

    new_week = {
        "date": week_end.isoformat(),
        "label": label,
        "albums": albums,
    }

    print("Fetching current data/releases.json from GitHub...")
    existing_json, _ = github_get_file("data/releases.json")
    weeks = json.loads(existing_json) if existing_json else []

    # Avoid duplicate entries if the task runs twice in the same week.
    weeks = [w for w in weeks if w["date"] != new_week["date"]]
    weeks.append(new_week)
    weeks.sort(key=lambda w: w["date"], reverse=True)  # newest first, even when repairing an old week

    print("Publishing to GitHub...")
    github_upsert_file(
        "data/releases.json",
        json.dumps(weeks, indent=2, ensure_ascii=False),
        f"Update release data for {new_week['date']}",
    )
    github_upsert_file(
        f"archive/{new_week['date']}.html",
        render_week_page(new_week),
        f"Add archive page for {new_week['date']}",
    )
    github_upsert_file(
        "archive/index.html",
        render_archive_index(weeks),
        f"Rebuild archive index ({new_week['date']})",
    )
    github_upsert_file(
        "index.html",
        render_index(weeks),
        f"Update homepage for {new_week['date']}",
    )

    print(f"Done. Published {new_week['label']}: {len(new_week['albums'])} albums.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — top-level task, want it logged clearly
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
