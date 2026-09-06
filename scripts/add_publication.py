#!/usr/bin/env python3
"""Add a publication to publications/index.html from its DOI.

Fetches metadata from Crossref, formats it in the ACS style already used on the
page, and inserts it at the top of the list with the next number.

    python3 scripts/add_publication.py 10.1021/acsenergylett.6c00550
    python3 scripts/add_publication.py 10.1021/... --dry-run
"""

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PUBS = REPO / "publications" / "index.html"

# Crossref sometimes returns the full journal name where the page uses an
# abbreviation. Extend this map as new venues show up.
ABBREV = {
    "Advanced Energy Materials": "Adv. Energy Mater.",
    "Advanced Materials": "Adv. Mater.",
    "Advanced Functional Materials": "Adv. Funct. Mater.",
    "Angewandte Chemie International Edition": "Angew. Chem. Int. Ed.",
    "Nature Communications": "Nat. Commun.",
    "Nature Materials": "Nat. Mater.",
    "Nature Energy": "Nat. Energy",
    "Nature Catalysis": "Nat. Catal.",
    "Journal of the American Chemical Society": "J. Am. Chem. Soc.",
    "Chemical Science": "Chem. Sci.",
    "Chemistry of Materials": "Chem. Mater.",
    "Energy & Environmental Science": "Energy Environ. Sci.",
    "Journal of Materials Chemistry A": "J. Mater. Chem. A",
    "Small": "Small",
    # Crossref's own short forms sometimes drop the periods the page uses.
    "Nat Commun": "Nat. Commun.",
    "Nat Mater": "Nat. Mater.",
    "Nat Energy": "Nat. Energy",
    "Nat Catal": "Nat. Catal.",
    "Nat Chem": "Nat. Chem.",
    "Sci Rep": "Sci. Rep.",
    "npj Comput Mater": "npj Comput. Mater.",
}

# U+2010 HYPHEN, U+2011 NON-BREAKING HYPHEN -> plain ASCII hyphen, so that
# "Seung\u2010Jae" still yields the "S.-J." initials the page uses.
HYPHENS = str.maketrans({"\u2010": "-", "\u2011": "-", "\u2212": "-"})

ENTRY = """        <div class="bg-white p-4 rounded-xl shadow-md border-l-4 border-red-500">
            <p class="text-lg font-semibold" style="color:var(--color-lab-primary-dark);">{n}. <a href="{url}" target="_blank" class="hover:underline" style="color:var(--color-lab-primary-dark);">{title}</a></p>
            <p class="text-gray-600">{authors} <span class="text-sm italic text-gray-500">{venue}</span></p>
        </div>
"""


def fetch(doi):
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]
    url = f"https://api.crossref.org/works/{urllib.parse.quote(doi, safe='/')}"
    req = urllib.request.Request(
        url, headers={"User-Agent": "THEMMES-site/1.0 (mailto:seungjae.shin@unist.ac.kr)"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return doi, json.load(r)["message"]
    except urllib.error.HTTPError as e:
        sys.exit(f"Crossref lookup failed for {doi}: HTTP {e.code}")
    except urllib.error.URLError as e:
        sys.exit(f"Crossref lookup failed for {doi}: {e.reason}")


def initials(given):
    """'Seung-Jae' -> 'S.-J.',  'Aron' -> 'A.',  'J. R.' -> 'J. R.'"""
    parts = [p for p in re.split(r"\s+", given.translate(HYPHENS).strip()) if p]
    out = []
    for p in parts:
        out.append("-".join(f"{seg[0]}." for seg in p.split("-") if seg))
    return " ".join(out)


def format_authors(msg):
    names = []
    for a in msg.get("author", []):
        family = a.get("family")
        if not family:
            if a.get("name"):
                names.append(a["name"])
            continue
        given = a.get("given", "")
        names.append(f"{family}, {initials(given)}" if given else family)
    if not names:
        return ""
    joined = "; ".join(names)
    return joined if joined.endswith(".") else joined + "."


def year_of(msg):
    for key in ("published-print", "published-online", "published", "issued", "created"):
        parts = msg.get(key, {}).get("date-parts") or []
        if parts and parts[0] and parts[0][0]:
            return str(parts[0][0])
    return ""


def format_venue(msg):
    short = msg.get("short-container-title") or []
    full = msg.get("container-title") or []
    journal = (short[0] if short else (full[0] if full else "")).strip()
    journal = ABBREV.get(journal, journal)
    if journal and not short and journal not in ABBREV.values() and " " in journal:
        print(f"note: no standard abbreviation known for {journal!r} "
              f"(use --journal to override, or add it to ABBREV)", file=sys.stderr)
    year = year_of(msg)
    bits = f"{journal} {year}".strip()

    volume = (msg.get("volume") or "").strip()
    issue = (msg.get("issue") or "").strip()
    page = (msg.get("page") or "").strip().replace("-", "–")
    art = (msg.get("article-number") or "").strip()

    tail = []
    if volume:
        tail.append(f"{volume} ({issue})" if issue else volume)
    if page:
        tail.append(page)
    elif art:
        tail.append(art)

    return f"{bits}, {', '.join(tail)}." if tail else f"{bits}."


def clean_title(msg):
    titles = msg.get("title") or []
    if not titles:
        sys.exit("Crossref record has no title.")
    t = titles[0]
    t = re.sub(r"\s*</?(sub|sup)>\s*", "", t)      # "Sp <sup>2</sup>" -> "Sp2"
    t = re.sub(r"<[^>]+>", "", t)                  # drop <i>, <scp>, ...
    t = html.unescape(t).translate(HYPHENS)
    t = re.sub(r"\s+([-,;:.)])", r"\1", t)         # tag removal can leave gaps
    t = re.sub(r"([(])\s+", r"\1", t)
    return html.escape(re.sub(r"\s+", " ", t).strip(), quote=False)


def next_number(page):
    nums = re.findall(r'-dark\);">(\d+)\. <a href=', page)
    return max(int(n) for n in nums) + 1 if nums else 1


def main():
    ap = argparse.ArgumentParser(description="Add a publication from its DOI.")
    ap.add_argument("doi", help="DOI, e.g. 10.1021/acsenergylett.6c00550")
    ap.add_argument("--dry-run", action="store_true", help="print the entry, do not write")
    ap.add_argument("--title", help="override the title (Crossref casing is often wrong)")
    ap.add_argument("--authors", help="override the author string, already formatted")
    ap.add_argument("--venue", help="override the whole journal/year/volume string")
    args = ap.parse_args()

    doi, msg = fetch(args.doi)
    page = PUBS.read_text(encoding="utf-8")
    url = f"https://doi.org/{doi}"

    if url in page:
        sys.exit(f"Already listed: {url}")

    number = next_number(page)
    entry = ENTRY.format(
        n=number,
        url=html.escape(url, quote=True),
        title=html.escape(args.title, quote=False) if args.title else clean_title(msg),
        authors=args.authors or format_authors(msg),
        venue=args.venue or format_venue(msg),
    )

    if args.dry_run:
        print(entry, end="")
        return

    anchor = '    <div class="space-y-4">\n'
    if anchor not in page:
        sys.exit("Could not find the publication list container in publications/index.html")
    page = page.replace(anchor, anchor + "\n" + entry, 1)
    PUBS.write_text(page, encoding="utf-8")
    print(f"Added #{number}: {url}")


if __name__ == "__main__":
    main()
