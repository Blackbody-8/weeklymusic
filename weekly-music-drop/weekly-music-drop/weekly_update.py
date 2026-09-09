"""
Weekly Music Drop
=================
Asks Gemini for the past week's notable music releases and publishes the
result to a GitHub Pages site.

Run this once a week (e.g. every Friday) as a PythonAnywhere scheduled task:
    python3 /home/YOURUSERNAME/weekly-music-drop/weekly_update.py

Requires a `secrets_config.py` file in the same folder (see
secrets_config.py.example) — that file is never committed to git.
"""

import base64
import datetime
import json
import re
import sys

import requests

import secrets_config as cfg

GEMINI_MODEL = "gemini-2.5-flash"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent"
)
GITHUB_API = "https://api.github.com"

SITE_TITLE = "Weekly Music Drop"


# ---------------------------------------------------------------------------
# 1. Ask Gemini what came out this week
# ---------------------------------------------------------------------------

def ask_gemini_for_releases(week_start, week_end):
    prompt = f"""You are a music-industry release tracker. Using up-to-date web search,
find the notable music released between {week_start:%B %d} and {week_end:%B %d}, {week_end.year}
(actual release dates that week, not announcements or upcoming releases).

Focus on releases a mainstream music fan would recognize — major-label and
well-known independent artists. Skip obscure catalogue reissues and deluxe
re-releases unless they're a genuinely big deal.

Reply with ONLY a JSON object and nothing else — no markdown fences, no
commentary before or after — in exactly this shape:

{{
  "albums": [{{"artist": "Artist Name", "title": "Album Title"}}],
  "singles_eps": [{{"artist": "Artist Name", "title": "Song Title", "is_ep": false}}]
}}

For collaborations/features, format the artist field like this:
"Kane Brown ft. Shania Twain". Set "is_ep" to true for EPs, false for singles.
Order both lists roughly by prominence, most notable first. If you genuinely
find nothing for a category, return an empty list for it — do not invent
releases.
"""

    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2},
    }

    resp = requests.post(GEMINI_URL, params={"key": cfg.GEMINI_API_KEY}, json=body, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise RuntimeError(f"Unexpected Gemini response shape: {json.dumps(data)[:500]}")

    # Gemini sometimes wraps JSON in ```json fences even when asked not to.
    cleaned = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        raise RuntimeError(f"Could not parse Gemini's reply as JSON:\n{text[:1000]}")


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
    singles = week.get("singles_eps", [])

    html = ""
    if albums:
        html += '<h3>Albums</h3>\n<ul class="releases">\n'
        for a in albums:
            html += f'  <li><span class="artist">{esc(a["artist"])}</span> &ndash; {esc(a["title"])}</li>\n'
        html += "</ul>\n"

    if singles:
        html += '<h3>Singles &amp; EPs</h3>\n<ul class="releases">\n'
        for s in singles:
            title = esc(s["title"])
            if s.get("is_ep"):
                title += " (EP)"
            else:
                title = f'&ldquo;{title}&rdquo;'
            html += f'  <li><span class="artist">{esc(s["artist"])}</span> &ndash; {title}</li>\n'
        html += "</ul>\n"

    if not albums and not singles:
        html += "<p><em>No notable releases found this week.</em></p>\n"

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
  <p class="tagline">New music, every Friday.</p>
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
        description=f'Music released the week of {week["label"]}.',
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
        description="What music came out this week, curated automatically every Friday.",
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
        description="Every past week of new music releases.",
        css_path="../",
        root_path="../",
        site_title=SITE_TITLE,
        body=body,
    )


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------

def main():
    today = datetime.date.today()
    # "This week" = the 7 days ending today (run this on Fridays).
    week_end = today
    week_start = today - datetime.timedelta(days=6)
    label = f"Week of {week_start:%B %-d}\u2013{week_end:%-d, %Y}" if week_start.month == week_end.month \
        else f"Week of {week_start:%B %-d} \u2013 {week_end:%B %-d, %Y}"

    print(f"Asking Gemini about releases from {week_start} to {week_end}...")
    result = ask_gemini_for_releases(week_start, week_end)

    new_week = {
        "date": week_end.isoformat(),
        "label": label,
        "albums": result.get("albums", []),
        "singles_eps": result.get("singles_eps", []),
    }

    print("Fetching current data/releases.json from GitHub...")
    existing_json, _ = github_get_file("data/releases.json")
    weeks = json.loads(existing_json) if existing_json else []

    # Avoid duplicate entries if the task runs twice in the same week.
    weeks = [w for w in weeks if w["date"] != new_week["date"]]
    weeks.insert(0, new_week)

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

    print(f"Done. Published {new_week['label']}: "
          f"{len(new_week['albums'])} albums, {len(new_week['singles_eps'])} singles/EPs.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 — top-level task, want it logged clearly
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
