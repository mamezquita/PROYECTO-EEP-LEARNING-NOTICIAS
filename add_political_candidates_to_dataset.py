"""
Merge satirical_candidates_political.csv into dataset_politica_colombiana.xlsx.

For each candidate URL (already classified as Colombian political satire and
confirmed absent from the dataset by scrape_satirical_sources.py), this:
  1. Re-fetches the article to get a clean body-derived description (matches
     the dataset's own style better than a truncated meta description) and a
     publish date.
       - elchiguirebipolar.net embeds its publish date directly in the URL
         path (DD-MM-YYYY/slug), no fetch needed for that part.
       - actualidadpanamericana.com prints it in a "Publicado el D mes, YYYY"
         byline at the top of the article body.
  2. Cleans the title (strips the site's " - Actualidad Panamericana" /
     " | El Chigüire Bipolar" suffix).
  3. Appends a new row (id, label=FALSE, title, description, date, url) to
     the dataset, continuing the id sequence from the current max.

Before writing, the original file is copied to
dataset_politica_colombiana.backup_pre_expansion.xlsx so the merge can be
undone if something looks wrong after review.
"""
import csv
import os
import re
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import openpyxl

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from scrape_satirical_sources import (  # noqa: E402
    fetch_url, domain_of, normalize_url, ARTICLE_FETCH_WORKERS,
)
from bs4 import BeautifulSoup  # noqa: E402

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(REPO_DIR, "dataset_politica_colombiana.xlsx")
BACKUP_PATH = os.path.join(REPO_DIR, "dataset_politica_colombiana.backup_pre_expansion.xlsx")
CANDIDATES_PATH = os.path.join(REPO_DIR, "satirical_candidates_political.csv")
FAILURES_PATH = os.path.join(REPO_DIR, "dataset_merge_failures.csv")

TITLE_SUFFIX_RE = re.compile(
    r"\s*[-|]\s*(Actualidad Panamericana|El Chig[üu]ire Bipolar)\s*$", re.IGNORECASE
)

MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}
AP_DATE_RE = re.compile(
    r"Publicado el\s+(\d{1,2})\s*(?:de\s+)?([A-Za-zñÁÉÍÓÚáéíóú]+)\s*,?\s*(?:de\s+)?(\d{4})",
    re.IGNORECASE,
)
CHIGUIRE_URL_DATE_RE = re.compile(r"/(\d{2})-(\d{2})-(\d{4})/")


def clean_title(raw_title: str) -> str:
    return TITLE_SUFFIX_RE.sub("", raw_title or "").strip()


def extract_ap_content(url: str):
    """Returns (description, date_str) for an actualidadpanamericana.com article."""
    html = fetch_url(url)
    soup = BeautifulSoup(html, "html.parser")
    paras = soup.select("div.entry-content p") or soup.select("article p")
    full_text = " ".join(p.get_text(" ", strip=True) for p in paras)

    date_str = ""
    m = AP_DATE_RE.search(full_text)
    if m:
        day, month_name, year = m.groups()
        month_num = MONTHS_ES.get(month_name.lower())
        if month_num:
            date_str = f"{int(day):02d}/{month_num:02d}/{year}"

    # Strip the "Publicado el ... ." byline prefix to get the real lede.
    body = AP_DATE_RE.sub("", full_text, count=1)
    body = re.sub(r"^\s*por\s+\S+\s+en\s+[^.]*\.\s*", "", body, flags=re.IGNORECASE)
    body = body.strip()

    description = body[:500].strip()
    if description and not description.endswith((".", "…", "!", "?")):
        # cut at the last full sentence within the first 500 chars if possible
        last_period = description.rfind(". ")
        if last_period > 80:
            description = description[: last_period + 1]
    return description, date_str


def extract_chiguire_date(url: str) -> str:
    m = CHIGUIRE_URL_DATE_RE.search(url)
    if not m:
        return ""
    day, month, year = m.groups()
    return f"{day}/{month}/{year}"


def main():
    print("Loading candidates...")
    with open(CANDIDATES_PATH, newline="", encoding="utf-8") as f:
        candidates = list(csv.DictReader(f))
    print(f"  {len(candidates)} political candidates to merge")

    print("Loading dataset...")
    wb = openpyxl.load_workbook(DATASET_PATH)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = rows[0]
    existing_ids = [int(r[0]) for r in rows[1:] if r[0] is not None]
    existing_urls = {normalize_url(str(r[5])) for r in rows[1:] if r[5]}
    next_id = max(existing_ids) + 1
    print(f"  {len(existing_ids)} existing rows, next id = {next_id}")
    print(f"  header: {header}")

    print(f"\nBacking up original dataset to {BACKUP_PATH}")
    shutil.copyfile(DATASET_PATH, BACKUP_PATH)

    to_process = []
    skipped_dupe = 0
    for cand in candidates:
        if normalize_url(cand["url"]) in existing_urls:
            skipped_dupe += 1
        else:
            to_process.append(cand)

    def process_one(cand):
        url = cand["url"]
        dom = domain_of(url)
        title = clean_title(cand["title"])

        try:
            if dom == "elchiguirebipolar.net":
                date_str = extract_chiguire_date(url)
                description = cand.get("description", "").strip()
                if len(description) < 40:
                    html = fetch_url(url)
                    soup = BeautifulSoup(html, "html.parser")
                    paras = [p.get_text(" ", strip=True) for p in soup.select("article p")]
                    paras = [p for p in paras if len(p) > 40]
                    description = paras[0][:500] if paras else description
            elif dom == "actualidadpanamericana.com":
                description, date_str = extract_ap_content(url)
                if len(description) < 40:
                    description = cand.get("description", "").strip()
            else:
                return {"url": url, "error": f"unknown domain {dom}"}
        except Exception as e:
            return {"url": url, "error": str(e)}

        if not description:
            description = title  # last-resort fallback, never leave it empty

        return {"title": title, "description": description, "date": date_str, "url": url}

    print(f"\nFetching/processing {len(to_process)} candidates with "
          f"{ARTICLE_FETCH_WORKERS} concurrent workers...")

    results, failures = [], []
    done = 0
    with ThreadPoolExecutor(max_workers=ARTICLE_FETCH_WORKERS) as pool:
        futures = {pool.submit(process_one, c): c for c in to_process}
        for fut in as_completed(futures):
            r = fut.result()
            done += 1
            if "error" in r:
                failures.append(r)
            else:
                results.append(r)
            if done % 100 == 0 or done == len(to_process):
                print(f"  ...{done}/{len(to_process)} processed "
                      f"({len(results)} ok, {len(failures)} failed)")

    # Assign ids in a stable order (by original candidate order) now that all
    # fetches are done — concurrency only affected fetch order, not this.
    url_order = {c["url"]: i for i, c in enumerate(to_process)}
    results.sort(key=lambda r: url_order.get(r["url"], 0))

    new_rows = []
    for r in results:
        new_rows.append({
            "id": str(next_id),
            "label": "FALSE",
            "title": r["title"],
            "description": r["description"],
            "date": r["date"],
            "url": r["url"],
        })
        next_id += 1

    print(f"\nAppending {len(new_rows)} new rows to the dataset...")
    for r in new_rows:
        ws.append([r["id"], r["label"], r["title"], r["description"], r["date"], r["url"]])

    wb.save(DATASET_PATH)
    print(f"Saved: {DATASET_PATH}")
    print(f"New row count: {len(existing_ids) + len(new_rows)} "
          f"({len(existing_ids)} original + {len(new_rows)} added)")

    if failures:
        with open(FAILURES_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["url", "error"])
            writer.writeheader()
            writer.writerows(failures)
        print(f"\n{len(failures)} candidates failed to merge — see {FAILURES_PATH}")

    if skipped_dupe:
        print(f"{skipped_dupe} candidates were already in the dataset (skipped as duplicates)")

    print("\nSample of newly added rows:")
    for r in new_rows[:5]:
        print(f"  id={r['id']}  date={r['date'] or '(none)'}  {r['title']}")
        print(f"    {r['description'][:150]}")


if __name__ == "__main__":
    main()
