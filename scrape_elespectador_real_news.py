"""
Pull real (TRUE-labeled) Colombian political news from elespectador.com to
balance the dataset's class distribution.

elespectador.com was chosen because:
  - It's already the dataset's single largest real-news source (190 of the
    original 403 TRUE rows).
  - Its robots.txt has no AI-training restriction of any kind (unlike
    eltiempo.com and portafolio.co, which explicitly block ClaudeBot/
    anthropic-ai by name and were excluded from this project for that
    reason).
  - It publishes a dedicated, well-structured sitemap for its "politica"
    section (Arc Publishing CMS), which means we get exact section
    membership for free — far more reliable than keyword-guessing whether an
    article is political, and each entry includes <lastmod> (publish date)
    directly in the sitemap, so no extra fetch is needed just for the date.

Method:
  1. Sample sitemap pages spread across the whole /politica/ archive (not
     just the most recent ones) for temporal diversity — same principle as
     the satire-site classifier, applied to a much cleaner signal (URL
     section) instead of keyword matching.
  2. For each URL not already in the dataset, fetch the article and pull its
     real <title>/og:title and meta description.
  3. Append as label=TRUE rows, continuing the dataset's id sequence.
"""
import csv
import html
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import openpyxl
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_satirical_sources import fetch_url, normalize_url  # noqa: E402

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(REPO_DIR, "dataset_politica_colombiana.xlsx")
BACKUP_PATH = os.path.join(REPO_DIR, "dataset_politica_colombiana.backup_pre_realnews_expansion.xlsx")
OUT_CSV = os.path.join(REPO_DIR, "elespectador_real_news_added.csv")

SITEMAP_INDEX = "https://www.elespectador.com/arc/outboundfeeds/sitemap-index/section/politica/?outputType=xml"
ARTICLE_WORKERS = 8
TARGET_NEW_ROWS = 1130  # FALSE=1626, TRUE=503 after first (partial, buggy) run — this closes the gap

SITEMAP_ENTRY_RE = re.compile(
    r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", re.S
)
TITLE_SUFFIX_RE = re.compile(r"\s*[|\-]\s*El Espectador\s*$", re.IGNORECASE)


def get_sitemap_page_entries(page_url: str):
    xml = fetch_url(page_url, timeout=20)
    return SITEMAP_ENTRY_RE.findall(xml)


def get_all_politica_subpages():
    index_xml = fetch_url(SITEMAP_INDEX, timeout=20)
    # sitemap XML HTML-escapes "&" as "&amp;" inside <loc> — these URLs get
    # used directly as request URLs, so they must be unescaped first or every
    # "&size=...&from=..." collapses into a malformed query string and the
    # server silently ignores the pagination, returning the same page
    # every time (this bit us on the first run: 21 "different" pages all
    # returned the same 100 URLs).
    return [html.unescape(u) for u in re.findall(r"<loc>([^<]+)</loc>", index_xml)]


def fetch_article(url: str):
    html = fetch_url(url)
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    if not title and soup.title and soup.title.string:
        title = soup.title.string.strip()
    title = TITLE_SUFFIX_RE.sub("", title).strip()

    description = ""
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip()
    if not description:
        meta_desc = soup.find("meta", attrs={"name": "description"})
        if meta_desc and meta_desc.get("content"):
            description = meta_desc["content"].strip()

    return title, description


def load_existing_urls():
    wb = openpyxl.load_workbook(DATASET_PATH, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    existing_ids = [int(r[0]) for r in rows[1:] if r[0] is not None]
    existing_urls = {normalize_url(str(r[5])) for r in rows[1:] if r[5]}
    return existing_ids, existing_urls


def main():
    print("Loading existing dataset...")
    existing_ids, existing_urls = load_existing_urls()
    next_id = max(existing_ids) + 1
    print(f"  {len(existing_ids)} existing rows, next id = {next_id}")

    print("\nDiscovering politica sitemap sub-pages...")
    subpages = get_all_politica_subpages()
    print(f"  {len(subpages)} sub-pages available (100 URLs each, spans the full archive)")

    # Sample spread across the whole archive for temporal diversity, not just
    # the most recent batch.
    step = max(1, len(subpages) // 20)
    sampled_pages = subpages[::step]
    print(f"  sampling {len(sampled_pages)} pages spread across the archive")

    print("\nCollecting candidate URLs from sampled pages...")
    all_entries = {}
    for i, page_url in enumerate(sampled_pages, 1):
        try:
            entries = get_sitemap_page_entries(page_url)
        except Exception as e:
            print(f"  page {i} failed: {e}")
            continue
        for loc, lastmod in entries:
            if normalize_url(loc) not in existing_urls:
                all_entries[loc] = lastmod
        if i % 5 == 0:
            print(f"  ...{i}/{len(sampled_pages)} pages, {len(all_entries)} new candidate URLs so far")

    print(f"\nTotal new candidate URLs: {len(all_entries)}")
    candidates = list(all_entries.items())[:int(TARGET_NEW_ROWS * 1.15)]  # small buffer for failures
    print(f"Using {len(candidates)} candidates (buffered above target {TARGET_NEW_ROWS})")

    print(f"\nFetching {len(candidates)} articles with {ARTICLE_WORKERS} workers...")
    results = []
    failures = 0
    done = 0
    with ThreadPoolExecutor(max_workers=ARTICLE_WORKERS) as pool:
        futures = {pool.submit(fetch_article, url): (url, lastmod) for url, lastmod in candidates}
        for fut in as_completed(futures):
            url, lastmod = futures[fut]
            done += 1
            try:
                title, description = fut.result()
                if title and description and len(description) > 20:
                    try:
                        date_str = datetime.fromisoformat(lastmod.replace("Z", "+00:00")).strftime("%d/%m/%Y")
                    except Exception:
                        date_str = ""
                    results.append({"title": title, "description": description, "date": date_str, "url": url})
                else:
                    failures += 1
            except Exception:
                failures += 1
            if done % 150 == 0 or done == len(candidates):
                print(f"  ...{done}/{len(candidates)} fetched ({len(results)} ok, {failures} failed)")

    print(f"\nGot {len(results)} usable articles (target was {TARGET_NEW_ROWS})")
    results = results[:TARGET_NEW_ROWS]

    print(f"\nBacking up dataset to {BACKUP_PATH}")
    shutil.copyfile(DATASET_PATH, BACKUP_PATH)

    wb = openpyxl.load_workbook(DATASET_PATH)
    ws = wb.active
    for r in results:
        ws.append([str(next_id), "TRUE", r["title"], r["description"], r["date"], r["url"]])
        next_id += 1
    wb.save(DATASET_PATH)
    print(f"Saved. Added {len(results)} TRUE rows.")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["title", "description", "date", "url"])
        writer.writeheader()
        writer.writerows(results)
    print(f"Also wrote a record to {OUT_CSV}")

    print("\nSample:")
    for r in results[:5]:
        print(f"  [{r['date']}] {r['title'][:80]}")


if __name__ == "__main__":
    main()
