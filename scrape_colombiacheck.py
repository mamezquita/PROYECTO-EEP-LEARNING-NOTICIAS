"""
Find Colombiacheck.com fact-checks (Colombian political claims rated false/
misleading) that aren't yet in dataset_politica_colombiana.xlsx.

Scope note: this script deliberately only targets colombiacheck.com. Two
other fact-checkers already represented in the dataset were evaluated and
excluded:
  - lasillavacia.com: its robots.txt explicitly disallows AI-training
    crawlers by name (ClaudeBot, anthropic-ai, GPTBot, CCBot, etc.) under a
    section titled "Entrenamiento de IA (no Google) - BLOQUEADOS". Since this
    script builds ML training data, that's exactly the use their policy
    targets, so it is not scraped here.
  - factual.afp.com: returns HTTP 403 from Akamai bot-protection on even a
    plain robots.txt request. Not attempted.
  colombiacheck.com's robots.txt has no AI-specific restriction, just
  standard Drupal admin paths blocked.

Method:
  1. Colombiacheck embeds each fact-check's verdict as schema.org ClaimReview
     JSON-LD (claimReviewed, reviewBody, datePublished, reviewRating with an
     alternateName like "Falso"/"Cuestionable"/"Verdadero"). This is far more
     reliable than scraping visible text.
  2. Crawl the paginated /chequeos listing (9 articles/page) to collect
     article URLs.
  3. For each article, extract every ClaimReview block. Skip ones rated
     clearly true ("Verdadero"/"Cierto") — those aren't fake news. Everything
     else (Falso, Cuestionable, Engañoso, etc.) matches the dataset's own
     existing convention: every one of the 111 pre-existing Colombiacheck
     rows in the dataset is labeled FALSE regardless of the exact nuance of
     the original rating.
  4. Skip claims already present in the dataset (matched on URL + claim text).

Output: colombiacheck_candidates.csv — NOT auto-merged into the dataset.
Review before merging, same as the satire pipeline.
"""
import csv
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_satirical_sources import (  # noqa: E402
    fetch_url, normalize_text, has_any_phrase,
    STRONG_POLITICAL_SIGNALS, WEAK_COLOMBIA_SIGNALS, POLITICAL_CONTEXT_TERMS,
)

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(REPO_DIR, "dataset_politica_colombiana.xlsx")
OUT_CSV = os.path.join(REPO_DIR, "colombiacheck_candidates.csv")

BASE = "https://colombiacheck.com"
LISTING_URL = BASE + "/chequeos"
MAX_LISTING_PAGES = 150          # ~1350 articles at 9/page
LISTING_WORKERS = 6
ARTICLE_WORKERS = 8

TRUE_RATINGS = {"verdadero", "cierto", "correcto"}

JSONLD_RE = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def get_listing_page_urls(page: int):
    html = fetch_url(f"{LISTING_URL}?page={page}", timeout=15)
    return sorted(set(re.findall(r'href="(/chequeos/[^"?#]+)"', html)))


def crawl_listing():
    print(f"Crawling up to {MAX_LISTING_PAGES} listing pages...")
    all_paths = set()
    empty_streak = 0
    with ThreadPoolExecutor(max_workers=LISTING_WORKERS) as pool:
        futures = {pool.submit(get_listing_page_urls, p): p for p in range(MAX_LISTING_PAGES)}
        results = {}
        for fut in as_completed(futures):
            p = futures[fut]
            try:
                results[p] = fut.result()
            except Exception as e:
                results[p] = []
                print(f"  page {p} failed: {e}")

    for p in range(MAX_LISTING_PAGES):
        paths = results.get(p, [])
        before = len(all_paths)
        all_paths.update(paths)
        if len(all_paths) == before:
            empty_streak += 1
        else:
            empty_streak = 0

    print(f"  collected {len(all_paths)} unique article paths")
    return [BASE + p for p in all_paths]


def extract_claims(url: str):
    """Returns list of dicts: claim, description, date_str, rating."""
    html = fetch_url(url, timeout=15)
    claims = []
    for block in JSONLD_RE.findall(html):
        try:
            data = json.loads(block)
        except Exception:
            continue
        graph = data.get("@graph", [])
        if isinstance(graph, dict):
            graph = [graph]
        if data.get("@type") == "ClaimReview":
            graph = graph + [data]
        for item in graph:
            if item.get("@type") != "ClaimReview":
                continue
            claim = (item.get("claimReviewed") or "").strip()
            if not claim:
                continue
            review_body = item.get("reviewBody") or ""
            if isinstance(review_body, list):
                review_body = " ".join(review_body)
            rating = item.get("reviewRating", {}) or {}
            alt_name = (rating.get("alternateName") or "").strip()
            date_raw = item.get("datePublished") or ""
            date_str = ""
            if date_raw:
                try:
                    date_str = datetime.fromisoformat(date_raw).strftime("%d/%m/%Y")
                except Exception:
                    pass
            claims.append({
                "claim": claim,
                "description": review_body.strip(),
                "date": date_str,
                "rating": alt_name,
                "url": url,
            })
    return claims


# The whole site is Colombia-scoped, so (unlike the satire-site classifier
# this borrows from) we don't also require a place-name signal here — that
# requirement existed to separate Colombia from the rest of Latin America on
# multi-country satire sites, which doesn't apply to a Colombia-only
# fact-checker. We do still filter for POLITICAL content specifically, since
# colombiacheck also fact-checks health/crime/viral-hoax claims unrelated to
# politics.
#
# Also extends the imported (older) political-figure list with current
# 2026-era names that postdate it, since Colombia had a presidential
# transition after the original list was built.
EXTRA_STRONG_SIGNALS = {
    "de la espriella", "abelardo de la espriella", "presidencia de la espriella",
}
EXTRA_CONTEXT_TERMS = {
    # NOTE: generic legal/crime words (condenado, sentencia, fiscalia, corte,
    # sancion) were tried and dropped here — same lesson as "gobierno"/
    # "policia" in scrape_satirical_sources.py: too common in ordinary,
    # non-political crime stories. "Contratista(s)" is kept because public
    # contracting fraud is specifically a political-corruption signal.
    "contratista", "contratistas", "contratacion publica", "presidenta",
}


def is_colombian_political(claim: str, description: str) -> bool:
    text = normalize_text(f"{claim} . {description}")
    if has_any_phrase(text, STRONG_POLITICAL_SIGNALS | EXTRA_STRONG_SIGNALS):
        return True
    return has_any_phrase(text, POLITICAL_CONTEXT_TERMS | EXTRA_CONTEXT_TERMS)


def load_existing_claims():
    wb = openpyxl.load_workbook(DATASET_PATH, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    col = {name: idx for idx, name in enumerate(header)}
    existing = set()
    for r in rows[1:]:
        if r is None:
            continue
        url = str(r[col["url"]] or "")
        title = normalize_text(str(r[col["title"]] or ""))
        if "colombiacheck.com" in url:
            existing.add((url.rstrip("/"), title))
    return existing


def main():
    print("Loading existing dataset claims (colombiacheck.com only)...")
    existing = load_existing_claims()
    print(f"  {len(existing)} existing (url, title) pairs from colombiacheck.com")

    urls = crawl_listing()

    print(f"\nFetching {len(urls)} articles with {ARTICLE_WORKERS} workers...")
    all_claims = []
    failures = 0
    done = 0
    with ThreadPoolExecutor(max_workers=ARTICLE_WORKERS) as pool:
        futures = {pool.submit(extract_claims, u): u for u in urls}
        for fut in as_completed(futures):
            done += 1
            try:
                all_claims.extend(fut.result())
            except Exception:
                failures += 1
            if done % 150 == 0 or done == len(urls):
                print(f"  ...{done}/{len(urls)} articles fetched "
                      f"({len(all_claims)} claims found so far, {failures} failed)")

    print(f"\nTotal claims extracted: {len(all_claims)}")

    true_rated = [c for c in all_claims if c["rating"].strip().lower() in TRUE_RATINGS]
    fake_rated = [c for c in all_claims if c["rating"].strip().lower() not in TRUE_RATINGS]
    print(f"  Rated true (excluded): {len(true_rated)}")
    print(f"  Rated false/misleading/other (candidate fake news): {len(fake_rated)}")

    political = [c for c in fake_rated if is_colombian_political(c["claim"], c["description"])]
    print(f"  Colombia-political among those: {len(political)}")

    new_ones = []
    for c in political:
        key = (c["url"].rstrip("/"), normalize_text(c["claim"]))
        if key not in existing:
            new_ones.append(c)
    print(f"  NOT already in dataset: {len(new_ones)}")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["claim", "description", "date", "rating", "url"])
        writer.writeheader()
        writer.writerows(new_ones)

    print(f"\nWritten: {OUT_CSV} ({len(new_ones)} rows)")
    print("\nSample:")
    for c in new_ones[:10]:
        print(f"  [{c['rating']}] {c['claim'][:80]}")
        print(f"      {c['url']}")


if __name__ == "__main__":
    main()
