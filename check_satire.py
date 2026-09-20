"""
Check whether every article sourced from known Colombian satirical/parody
news sites in dataset_politica_colombiana.xlsx is labeled as fake (label=False).

Known satirical domains present in this corpus (identified by manual review
of the URL column): actualidadpanamericana.com and elchiguirebipolar.net.
Both are self-described satire outlets, not real news.
"""
import os
from urllib.parse import urlparse
from openpyxl import load_workbook

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dataset_politica_colombiana.xlsx")

SATIRICAL_DOMAINS = {
    "actualidadpanamericana.com",
    "elchiguirebipolar.net",
}


def domain_of(url: str) -> str:
    if not url:
        return ""
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def normalize_label(raw):
    """Handle the label column being stored as text 'TRUE'/'FALSE' rather
    than a numeric 0/1, which is what actually happens in this xlsx."""
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    if isinstance(raw, str):
        s = raw.strip().upper()
        if s in ("TRUE", "1", "REAL"):
            return True
        if s in ("FALSE", "0", "FALSA", "FAKE"):
            return False
    return None  # unrecognized


def main():
    wb = load_workbook(PATH, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    data = rows[1:]

    col = {name: idx for idx, name in enumerate(header)}
    required = {"id", "label", "title", "url"}
    missing = required - set(col)
    if missing:
        raise SystemExit(f"Missing expected columns: {missing}. Found: {header}")

    total = 0
    satirical_rows = []
    label_parse_failures = []

    for r in data:
        if r is None or all(v is None for v in r):
            continue
        total += 1
        url = r[col["url"]] if col.get("url") is not None else None
        dom = domain_of(str(url)) if url else ""
        if dom in SATIRICAL_DOMAINS:
            raw_label = r[col["label"]]
            label = normalize_label(raw_label)
            if label is None:
                label_parse_failures.append((r[col["id"]], raw_label))
            satirical_rows.append({
                "id": r[col["id"]],
                "domain": dom,
                "title": r[col["title"]],
                "raw_label": raw_label,
                "label_is_real": label,
            })

    print(f"Total rows read: {total}")
    print(f"Rows sourced from known satirical domains: {len(satirical_rows)}")
    print(f"Domains checked: {sorted(SATIRICAL_DOMAINS)}\n")

    if label_parse_failures:
        print("!! Could not parse label for these rows:")
        for _id, raw in label_parse_failures:
            print(f"   id={_id} raw_label={raw!r}")
        print()

    mislabeled = [row for row in satirical_rows if row["label_is_real"] is True]
    correctly_labeled = [row for row in satirical_rows if row["label_is_real"] is False]

    print(f"Correctly labeled as FAKE (label=False/0): {len(correctly_labeled)}")
    print(f"INCORRECTLY labeled as REAL (label=True/1): {len(mislabeled)}\n")

    if mislabeled:
        print("Satirical-source rows labeled as REAL news (should be FAKE):")
        for row in mislabeled:
            print(f"  id={row['id']:>4}  domain={row['domain']:<30}  raw_label={row['raw_label']!r}")
            print(f"        title: {row['title']}")
    else:
        print("All rows sourced from satirical domains are correctly labeled as fake.")

    print("\nPer-domain breakdown:")
    for dom in sorted(SATIRICAL_DOMAINS):
        rows_d = [r for r in satirical_rows if r["domain"] == dom]
        fake_n = sum(1 for r in rows_d if r["label_is_real"] is False)
        real_n = sum(1 for r in rows_d if r["label_is_real"] is True)
        unk_n = sum(1 for r in rows_d if r["label_is_real"] is None)
        print(f"  {dom:<30} total={len(rows_d):<4} labeled_fake={fake_n:<4} labeled_real={real_n:<4} unparseable={unk_n}")


if __name__ == "__main__":
    main()
