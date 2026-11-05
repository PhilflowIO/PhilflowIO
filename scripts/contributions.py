#!/usr/bin/env python3
"""Render the "Open Source Contributions" section of the profile README.

Pulls every pull request authored by USER in repositories USER does not own,
groups merged ones by upstream project and rewrites the block between the
CONTRIB markers in README.md. Runs daily from .github/workflows/metrics.yml.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

USER = "PhilflowIO"
# Repos that are mine under another owner, not upstream work.
OWN_OWNERS = {"PhilflowIO", "PhilflowIOOrg"}
# Merged PRs that only add a list entry for one of my projects.
LISTING_REPOS = {"punkpeye/awesome-mcp-servers", "modelcontextprotocol/servers"}

README = Path(__file__).resolve().parent.parent / "README.md"
START, END = "<!-- CONTRIB:START -->", "<!-- CONTRIB:END -->"

QUERY = """
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      ... on PullRequest {
        state mergedAt title url
        repository {
          nameWithOwner url stargazerCount description
          owner { avatarUrl }
        }
      }
    }
  }
}
"""


def fetch(token: str) -> list[dict]:
    prs, after = [], None
    while True:
        body = json.dumps({"query": QUERY, "variables": {"q": f"author:{USER} is:pr -user:{USER}", "after": after}})
        req = urllib.request.Request(
            "https://api.github.com/graphql",
            data=body.encode(),
            headers={"Authorization": f"bearer {token}", "User-Agent": f"{USER}-profile"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.load(resp)
        if "errors" in data:
            raise RuntimeError(data["errors"])
        search = data["data"]["search"]
        prs += [n for n in search["nodes"] if n]
        if not search["pageInfo"]["hasNextPage"]:
            return prs
        after = search["pageInfo"]["endCursor"]


def stars(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def clean(title: str) -> str:
    # excelize convention: "This closes #2415, count an empty string in COUNTA"
    title = re.sub(r"^This closes #\d+,\s*", "", title)
    title = re.sub(r"^\w+(\([^)]*\))?!?:\s*", "", title)  # conventional-commit prefix
    return title[:1].upper() + title[1:]


def render(prs: list[dict]) -> str:
    merged, review, listed = defaultdict(list), defaultdict(list), {}
    for pr in prs:
        repo = pr["repository"]
        name = repo["nameWithOwner"]
        if name.split("/")[0] in OWN_OWNERS:
            continue
        if name in LISTING_REPOS:
            if pr["state"] == "MERGED":
                listed[name] = repo
            continue
        if pr["state"] == "MERGED":
            merged[name].append(pr)
        elif pr["state"] == "OPEN":
            review[name].append(pr)

    repos = {pr["repository"]["nameWithOwner"]: pr["repository"] for pr in prs}
    n_merged = sum(map(len, merged.values()))
    n_review = sum(map(len, review.values()))

    lines = [
        f"**{n_merged} merged pull requests in {len(merged)} upstream projects**"
        + (f" · {n_review} more in review" if n_review else ""),
        "",
        "| Project | ★ | Merged |",
        "|:--|--:|:--|",
    ]
    order = sorted(merged, key=lambda r: (-len(merged[r]), -repos[r]["stargazerCount"]))
    for name in order:
        repo, items = repos[name], sorted(merged[name], key=lambda p: p["mergedAt"], reverse=True)
        desc = (repo["description"] or "").strip().rstrip(".")
        head = (
            f'<img src="{repo["owner"]["avatarUrl"]}&s=40" width="20" height="20" align="center"> '
            f'**[{name}]({repo["url"]})**' + (f"<br><sub>{desc}</sub>" if desc else "")
        )
        work = "<br>".join(f"[{clean(p['title'])}]({p['url']})" for p in items)
        lines.append(f"| {head} | {stars(repo['stargazerCount'])} | {work} |")

    if review:
        open_order = sorted(review, key=lambda r: -repos[r]["stargazerCount"])
        lines += ["", "**In review:** " + " · ".join(
            f"[{n}]({repos[n]['url']}/pulls?q=author%3A{USER}+is%3Aopen) ({len(review[n])})" for n in open_order
        )]
    if listed:
        lines += ["", "**Listed in:** " + " · ".join(
            f"[{n}]({r['url']}) (★ {stars(r['stargazerCount'])})" for n, r in listed.items()
        )]
    return "\n".join(lines)


def main() -> int:
    token = os.environ.get("GITHUB_TOKEN") or os.environ["GH_TOKEN"]
    section = render(fetch(token))
    text = README.read_text()
    if START not in text or END not in text:
        sys.exit(f"markers {START} / {END} missing in {README}")
    before, rest = text.split(START, 1)
    _, after = rest.split(END, 1)
    README.write_text(f"{before}{START}\n{section}\n{END}{after}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
