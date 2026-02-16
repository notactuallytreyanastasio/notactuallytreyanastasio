import json
import os
import re
import requests

BSKY_API = "https://public.api.bsky.app/xrpc"
GITHUB_API = "https://api.github.com"
COMPUTER_EMOJI = "\U0001f4bb"


def load_config():
    with open("config.json") as f:
        return json.load(f)


def github_headers():
    token = os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def fetch_featured_repos(config):
    rows = []
    for repo in config["featured_repos"]:
        name = repo["name"]
        blurb = repo.get("blurb", "")
        r = requests.get(f"{GITHUB_API}/repos/{config['github_username']}/{name}", headers=github_headers())
        stars = 0
        lang = ""
        if r.status_code == 200:
            data = r.json()
            stars = data.get("stargazers_count", 0)
            lang = data.get("language") or ""
        url = f"https://github.com/{config['github_username']}/{name}"
        lang_str = f" `{lang}`" if lang else ""
        star_badge = f" &nbsp; :star: {stars}" if stars > 0 else ""
        rows.append(f"| [**{name}**]({url}){lang_str}{star_badge} | {blurb} |")
    header = "| Project | Description |\n| --- | --- |"
    return header + "\n" + "\n".join(rows)


def fetch_blog_allowed_slugs(config):
    """Fetch the allowed_slugs list from the blog's post.ex source."""
    r = requests.get(
        f"{GITHUB_API}/repos/{config['blog_repo']}/contents/lib/blog/content/post.ex",
        headers=github_headers(),
    )
    if r.status_code != 200:
        return None
    import base64
    content = base64.b64decode(r.json()["content"]).decode()
    m = re.search(r'@allowed_slugs ~w\((.*?)\)', content, re.DOTALL)
    if not m:
        return None
    return set(m.group(1).split())


def fetch_blog_posts(config):
    allowed = fetch_blog_allowed_slugs(config)

    r = requests.get(
        f"{GITHUB_API}/repos/{config['blog_repo']}/contents/priv/static/posts",
        headers=github_headers(),
    )
    if r.status_code != 200:
        return "_Could not fetch blog posts._"

    files = r.json()
    posts = []
    for f in files:
        name = f["name"]
        if not name.endswith(".md"):
            continue
        stem = name[:-3]
        # Skip hash-suffixed cache files
        parts = stem.rsplit("-", 1)
        if len(parts) == 2 and re.match(r"^[0-9a-f]{32}$", parts[1]):
            continue
        # Parse: YYYY-MM-DD-HH-MM-SS-slug.md
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-\d{2}-\d{2}-\d{2}-(.+)$", stem)
        if m:
            date_str = m.group(1)
            slug = m.group(2)
            if allowed is not None and slug not in allowed:
                continue
            posts.append((date_str, slug))

    posts.sort(key=lambda x: x[0], reverse=True)
    lines = []
    for _, slug in posts[:5]:
        title = slug.replace("-", " ").title()
        url = f"{config['blog_base_url']}/post/{slug}"
        lines.append(f"- [{title}]({url})")
    return "\n".join(lines) if lines else "_No blog posts found._"


def fetch_bluesky_threads(config):
    did = config["bluesky_did"]
    handle = config["bluesky_handle"]
    max_scan = config.get("bluesky_max_scan", 200)
    threads = []
    cursor = None
    scanned = 0

    while scanned < max_scan:
        limit = min(50, max_scan - scanned)
        params = {"actor": did, "limit": limit, "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor
        r = requests.get(f"{BSKY_API}/app.bsky.feed.getAuthorFeed", params=params)
        if r.status_code != 200:
            break
        data = r.json()
        feed = data.get("feed", [])
        if not feed:
            break

        for item in feed:
            post = item.get("post", {})
            if post.get("author", {}).get("did") != did:
                continue
            record = post.get("record", {})
            text = record.get("text", "")
            if COMPUTER_EMOJI in text:
                uri = post.get("uri", "")
                rkey = uri.split("/")[-1] if "/" in uri else ""
                preview = text[:200].replace("\n", " ")
                if len(text) > 200:
                    preview += "..."
                link = f"https://bsky.app/profile/{handle}/post/{rkey}"
                threads.append(f"- [{preview}]({link})")

        scanned += len(feed)
        cursor = data.get("cursor")
        if not cursor:
            break

    if not threads:
        return "_No tech threads yet. Posts with a computer emoji will appear here._"
    return "\n".join(threads[:5])


def fetch_recent_repos(config):
    featured_names = {r["name"] for r in config["featured_repos"]}
    r = requests.get(
        f"{GITHUB_API}/users/{config['github_username']}/repos",
        params={"sort": "pushed", "per_page": 30, "type": "owner"},
        headers=github_headers(),
    )
    if r.status_code != 200:
        return "_Could not fetch repos._"

    lines = []
    for repo in r.json():
        if repo.get("fork"):
            continue
        if repo["name"] in featured_names:
            continue
        if repo["name"] == config["github_username"]:
            continue
        desc = repo.get("description") or ""
        lang = repo.get("language") or ""
        suffix = f" `{lang}`" if lang else ""
        desc_str = f" - {desc}" if desc else ""
        lines.append(f"- [{repo['name']}]({repo['html_url']}){desc_str}{suffix}")
        if len(lines) >= 5:
            break
    return "\n".join(lines) if lines else "_No recent repos._"


def build_artsy_table(config):
    projects = config.get("artsy_projects", [])
    # Build a 4-column table
    cols = 4
    header = "| | | | |\n| --- | --- | --- | --- |"
    rows = []
    for i in range(0, len(projects), cols):
        chunk = projects[i:i + cols]
        cells = [f"[{p['label']}]({p['url']})" for p in chunk]
        while len(cells) < cols:
            cells.append("")
        rows.append("| " + " | ".join(cells) + " |")
    return header + "\n" + "\n".join(rows)


def build_readme(config):
    featured = fetch_featured_repos(config)
    artsy = build_artsy_table(config)
    blog = fetch_blog_posts(config)
    bluesky = fetch_bluesky_threads(config)
    recent = fetch_recent_repos(config)

    handle = config["bluesky_handle"]
    blog_url = config["blog_base_url"]

    return f"""# Bobby Grayson

Makin' silly & frivolous stuff, usually with software.

[Blog]({blog_url}) | [Bluesky](https://bsky.app/profile/{handle})

---

## Featured Projects
<!-- featured starts -->
{featured}
<!-- featured ends -->

## Artsy & Weird Things I'm Making Now, Check Out the READMEs
<!-- artsy starts -->
{artsy}
<!-- artsy ends -->

## Recent Blog Posts
<!-- blog starts -->
{blog}
<!-- blog ends -->

## Tech Threads (Bluesky)
<!-- bluesky starts -->
{bluesky}
<!-- bluesky ends -->

## Recently Updated
<!-- recent starts -->
{recent}
<!-- recent ends -->
"""


if __name__ == "__main__":
    config = load_config()
    readme = build_readme(config)
    with open("README.md", "w") as f:
        f.write(readme)
    print("README.md updated.")
