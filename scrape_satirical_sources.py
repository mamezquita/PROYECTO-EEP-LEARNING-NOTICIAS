"""
Cross-check dataset_politica_colombiana.xlsx against the live sitemaps of the
two known satirical sources already present in the corpus
(actualidadpanamericana.com, elchiguirebipolar.net) to find Colombia-political
satire that never made it into the dataset.

Two-stage classification:
  Stage 1 (recall, cheap): scan every sitemap URL's slug for any Colombia
      place/figure/institution token. This is deliberately broad — it's just
      there to shrink ~14,000 site-wide URLs down to a candidate set worth
      fetching, not the final answer.
  Stage 2 (precision, expensive): actually fetch each Stage-1 candidate page
      and read its real <title>, meta description, AND the first few
      paragraphs of the article body. Classify it as "Colombian political
      satire" if that text contains a Colombia signal AND a political-context
      term (government, elections, conflict, institutions, named politicians,
      municipal/administrative bodies, etc.) — or a signal that is itself
      unambiguously political (e.g. "farc", "congreso", a named president).
      All matching is whole-word / phrase, accent-insensitive, done on real
      article text — not URL substrings — specifically to avoid false hits
      like "petrolero" matching "petro" or "california" matching "cali".

      Earlier versions of this script classified off the meta description
      alone, which WordPress/Yoast truncates to ~155 characters — political
      signals that showed up later in the description or only in the body
      (e.g. "elecciones para la Alcaldía de Bogotá... destitución de Gustavo
      Petro" arriving after the truncation point) were missed. Pulling the
      first several body paragraphs fixes that class of false negative.

Output:
  - satirical_candidates_political.csv       -> classified as Colombian political satire, not in dataset
  - satirical_candidates_other.csv           -> Colombia-touching but NOT classified as political (sports, entertainment, etc.)
  - satirical_fetch_failures.csv             -> candidate URLs that couldn't be fetched/parsed
Console prints a summary. This is a classifier over public sitemap + article
metadata (title/meta description), not a guarantee — always skim before
merging any of this into the real dataset.
"""
import csv
import os
import re
import time
import unicodedata
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from openpyxl import load_workbook

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(REPO_DIR, "dataset_politica_colombiana.xlsx")
OUT_POLITICAL = os.path.join(REPO_DIR, "satirical_candidates_political.csv")
OUT_OTHER = os.path.join(REPO_DIR, "satirical_candidates_other.csv")
OUT_FAILURES = os.path.join(REPO_DIR, "satirical_fetch_failures.csv")

UA = "Mozilla/5.0 (compatible; dataset-coverage-check/1.0; academic project)"
SITEMAP_REQUEST_DELAY = 0.5   # seconds between sitemap-index fetches (few, sequential)
ARTICLE_FETCH_WORKERS = 8     # concurrent article fetches (politeness vs. speed)
ARTICLE_TIMEOUT = 12

SITES = {
    "actualidadpanamericana.com": {
        "sitemap_index": "https://actualidadpanamericana.com/sitemap.xml",
    },
    "elchiguirebipolar.net": {
        "sitemap_index": "https://www.elchiguirebipolar.net/wp-sitemap.xml",
    },
}

# ---------------------------------------------------------------------------
# Stage 1: cheap slug-level recall filter (place/figure/institution tokens)
# ---------------------------------------------------------------------------
SLUG_TOKENS = {
    "colombia", "colombiano", "colombiana", "colombianos", "colombianas",
    "bogota", "bogotano", "bogotana", "medellin", "cali", "barranquilla",
    "cartagena", "bucaramanga", "cundinamarca", "antioquia", "atlantico",
    "santander", "boyaca", "narino", "cauca", "cordoba", "tolima", "huila",
    "petro", "duque", "uribe", "uribista", "uribismo", "santos", "samper",
    "pastrana", "gaitan", "farc", "eln", "dane", "dnp", "minhacienda",
    "senado", "registraduria", "contraloria", "procuraduria",
    "defensoria", "esmad", "transmilenio", "petrista", "petrismo",
    "gustavo-petro", "ivan-duque", "alvaro-uribe", "francia-marquez",
    "claudia-lopez", "rodolfo-hernandez", "sergio-fajardo",
    "federico-gutierrez", "juan-manuel-santos",
}

# ---------------------------------------------------------------------------
# Stage 2: content-level classification (checked against real title+description)
# ---------------------------------------------------------------------------

# Signals that are ALREADY political on their own (named politicians,
# political institutions — national AND municipal/administrative — armed
# political actors) — one hit is enough. Institution words are included
# bare (not just as "X de Bogotá" exact phrases) because satire headlines
# name plenty of cities/departments beyond Bogotá.
STRONG_POLITICAL_SIGNALS = {
    "petro", "gustavo petro", "duque", "ivan duque", "uribe", "alvaro uribe",
    "uribista", "uribismo", "petrista", "petrismo", "santos",
    "juan manuel santos", "samper", "pastrana", "francia marquez",
    "claudia lopez", "rodolfo hernandez", "sergio fajardo",
    "federico gutierrez", "farc", "eln", "esmad", "congreso", "senado",
    "camara de representantes", "concejo", "concejo de bogota",
    "procuraduria", "contraloria", "defensoria del pueblo",
    "registraduria", "corte constitucional", "corte suprema",
    "casa de narino", "corte penal", "gobernacion", "alcaldia",
    "alcaldia de bogota", "minhacienda", "ministerio de hacienda",
    "ministerio de defensa", "dnp", "distrito", "distrito capital",
    "personeria", "veeduria", "curul", "concejal", "diputado",
    "paro nacional", "paro armado", "paro civico", "movilizacion social",
    "consulta popular", "consejo de estado", "junta directiva",
}

# Weak Colombia signals (place names) — need a political-context term too,
# since "Bogotá" or "Medellín" on their own could be sports/culture/crime satire.
WEAK_COLOMBIA_SIGNALS = {
    "colombia", "colombiano", "colombiana", "colombianos", "colombianas",
    "bogota", "bogotano", "bogotana", "medellin", "cali", "barranquilla",
    "cartagena", "bucaramanga", "cundinamarca", "antioquia",
    "valle del cauca", "atlantico", "santander", "boyaca", "narino",
    "cauca", "cordoba", "tolima", "huila", "dane",
}

POLITICAL_CONTEXT_TERMS = {
    # NOTE: bare "gobierno", "policia", "politica"/"politico" were tried and
    # dropped — this site uses them as a stock punchline ("el gobierno no
    # autorizo...") in jokes about anything (airline routes, perfume
    # launches), so on their own they're not a reliable political signal.
    # Specific phrases keep the genuine government-story recall without that
    # noise.
    "gobierno colombiano", "gobierno nacional", "gobierno distrital",
    "gobierno de bogota", "policia nacional", "presidente", "presidencia",
    "ministro", "ministra", "ministerio", "congreso", "senado", "senador",
    "senadora", "camara de representantes", "representante a la camara",
    "alcaldia", "alcalde", "alcaldesa", "gobernador", "gobernadora",
    "gobernacion", "corte constitucional", "corte suprema", "procuraduria",
    "contraloria", "defensoria", "registraduria", "eleccion", "elecciones",
    "campana", "campaña", "candidato", "candidata", "reforma tributaria",
    "reforma pensional", "reforma laboral", "reforma a la salud", "reforma",
    "decreto", "proyecto de ley", "impuesto", "impuestos", "paz total",
    "acuerdo de paz", "guerrilla", "paramilitar", "ejercito",
    "partido politico", "oposicion", "coalicion", "bancada",
    "concejal", "diputado", "mocion de censura", "revocatoria",
    "plebiscito", "referendo", "consulta popular", "corrupcion",
    "escandalo politico",
    "distrito", "secretaria de educacion", "secretaria de movilidad",
    "secretaria de salud", "secretaria de gobierno", "pot",
    "ordenamiento territorial", "licitacion", "contratacion publica",
    "obra publica", "paro nacional", "paro civico", "paro de transporte",
    "marcha de protesta", "protesta social", "movilizacion social",
    "curul", "acto legislativo",
    "salario minimo", "iva", "personeria", "veeduria",
}


def strip_accents(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    )


def normalize_text(s: str) -> str:
    return strip_accents(s.lower())


def has_any_phrase(text: str, phrases) -> bool:
    """Whole-word/phrase match on normalized text (word-boundary regex),
    so 'petro' doesn't match inside 'petrolero' and 'cali' doesn't match
    inside 'california'."""
    for phrase in phrases:
        pattern = r"\b" + re.escape(phrase) + r"\b"
        if re.search(pattern, text):
            return True
    return False


def fetch_url(url: str, timeout: int = ARTICLE_TIMEOUT, retries: int = 3) -> str:
    """Fetch with retry/backoff — actualidadpanamericana.com has shown
    transient timeouts under sustained request volume in this session,
    most likely mild rate-limiting rather than a real outage."""
    last_exc = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    raise last_exc


def extract_locs(xml_text: str):
    return re.findall(r"<loc>([^<]+)</loc>", xml_text)


def collect_all_urls(sitemap_index_url: str):
    index_xml = fetch_url(sitemap_index_url, timeout=20)
    time.sleep(SITEMAP_REQUEST_DELAY)
    sub_sitemaps = [u for u in extract_locs(index_xml) if "image-sitemap" not in u]

    all_urls = []
    for sm_url in sub_sitemaps:
        try:
            xml_text = fetch_url(sm_url, timeout=20)
        except Exception as e:
            print(f"    !! failed to fetch {sm_url}: {e}")
            continue
        time.sleep(SITEMAP_REQUEST_DELAY)
        locs = extract_locs(xml_text)
        if "<sitemapindex" in xml_text:
            for nested in locs:
                try:
                    nested_xml = fetch_url(nested, timeout=20)
                    all_urls.extend(extract_locs(nested_xml))
                except Exception as e:
                    print(f"    !! failed to fetch nested {nested}: {e}")
                time.sleep(SITEMAP_REQUEST_DELAY)
        else:
            all_urls.extend(locs)
    return all_urls


def normalize_url(url: str) -> str:
    p = urlparse(url.strip())
    netloc = p.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = p.path.rstrip("/")
    return f"{netloc}{path}"


def domain_of(url: str) -> str:
    netloc = urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


def slug_is_candidate(url: str) -> bool:
    slug = normalize_text(url)
    tokens = re.split(r"[^a-z0-9]+", slug)
    return any(tok in SLUG_TOKENS for tok in tokens)


def load_dataset_urls():
    wb = load_workbook(DATASET_PATH, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip().lower() if h is not None else "" for h in rows[0]]
    col = {name: idx for idx, name in enumerate(header)}
    if "url" not in col:
        raise SystemExit(f"No 'url' column found. Header: {header}")

    urls_by_domain = {}
    for r in rows[1:]:
        if r is None:
            continue
        url = r[col["url"]]
        if not url:
            continue
        url = str(url)
        dom = domain_of(url)
        urls_by_domain.setdefault(dom, set()).add(normalize_url(url))
    return urls_by_domain


BODY_PARAGRAPHS_TO_READ = 6  # enough to cover the lede on these sites without pulling whole pages

def fetch_article_content(url: str):
    """Returns (title, description, body_excerpt). `description` is the
    (often truncated) meta description; `body_excerpt` is the first few
    real paragraphs of the article, which is what actually catches signals
    that show up after the meta description's ~155-character cutoff."""
    html = fetch_url(url)
    soup = BeautifulSoup(html, "html.parser")

    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        title = og_title["content"].strip() or title

    description = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        description = meta_desc["content"].strip()
    og_desc = soup.find("meta", property="og:description")
    if og_desc and og_desc.get("content"):
        description = og_desc["content"].strip() or description

    paras = soup.select("div.entry-content p") or soup.select("article p")
    body_excerpt = " ".join(
        p.get_text(" ", strip=True) for p in paras[:BODY_PARAGRAPHS_TO_READ]
    )

    return title, description, body_excerpt


def classify(title: str, description: str, body_excerpt: str = ""):
    """Returns (is_political: bool, reason: str)."""
    text = normalize_text(f"{title} . {description} . {body_excerpt}")

    if has_any_phrase(text, STRONG_POLITICAL_SIGNALS):
        return True, "strong_political_signal"

    has_place = has_any_phrase(text, WEAK_COLOMBIA_SIGNALS)
    has_context = has_any_phrase(text, POLITICAL_CONTEXT_TERMS)
    if has_place and has_context:
        return True, "place+political_context"

    return False, "no_political_signal" if not has_place else "place_only_no_political_context"


def fetch_and_classify(url: str):
    try:
        title, description, body_excerpt = fetch_article_content(url)
    except Exception as e:
        return {"url": url, "error": str(e)}
    is_political, reason = classify(title, description, body_excerpt)
    return {
        "url": url,
        "title": title,
        "description": description,
        "is_political": is_political,
        "reason": reason,
    }


def main():
    print("Loading existing dataset URLs...")
    dataset_urls = load_dataset_urls()
    for dom, urls in dataset_urls.items():
        if dom in SITES:
            print(f"  {dom}: {len(urls)} URLs already in dataset")
    print()

    # ---- Stage 1: build candidate set per domain (slug recall filter, minus what's already in) ----
    stage1_candidates = []  # (domain, url)
    for domain, info in SITES.items():
        print(f"Crawling sitemap for {domain} ...")
        try:
            all_urls = collect_all_urls(info["sitemap_index"])
        except Exception as e:
            print(f"  !! could not crawl {domain}: {e}")
            continue
        print(f"  Total URLs on site: {len(all_urls)}")

        existing = dataset_urls.get(domain, set())
        slug_matches = [u for u in all_urls if slug_is_candidate(u)]
        new_ones = [u for u in slug_matches if normalize_url(u) not in existing]
        print(f"  Slug-level Colombia recall filter: {len(slug_matches)} "
              f"({len(new_ones)} not already in dataset)\n")
        stage1_candidates.extend(new_ones)

    print(f"Stage 1 candidate set (to be content-checked): {len(stage1_candidates)}")
    print(f"Fetching each candidate's real title/description with "
          f"{ARTICLE_FETCH_WORKERS} concurrent workers...\n")

    # ---- Stage 2: fetch + classify by actual content ----
    political, other, failures = [], [], []
    done = 0
    with ThreadPoolExecutor(max_workers=ARTICLE_FETCH_WORKERS) as pool:
        futures = {pool.submit(fetch_and_classify, url): url for url in stage1_candidates}
        for fut in as_completed(futures):
            result = fut.result()
            done += 1
            if done % 100 == 0 or done == len(stage1_candidates):
                print(f"  ...{done}/{len(stage1_candidates)} fetched")
            if "error" in result:
                failures.append(result)
            elif result["is_political"]:
                political.append(result)
            else:
                other.append(result)

    domain_of_url = lambda u: domain_of(u)

    print("\n" + "=" * 70)
    print("RESULTS")
    print("=" * 70)
    print(f"Fetched successfully : {len(political) + len(other)}")
    print(f"Fetch failures        : {len(failures)}")
    print(f"Classified POLITICAL  : {len(political)}")
    print(f"Classified other      : {len(other)}")

    for dom in SITES:
        n_pol = sum(1 for r in political if domain_of_url(r["url"]) == dom)
        n_oth = sum(1 for r in other if domain_of_url(r["url"]) == dom)
        n_fail = sum(1 for r in failures if domain_of_url(r["url"]) == dom)
        print(f"\n  {dom}:")
        print(f"    political : {n_pol}")
        print(f"    other     : {n_oth}")
        print(f"    failed    : {n_fail}")

    def write_csv(path, rows, fields):
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in fields})

    write_csv(OUT_POLITICAL, political, ["url", "title", "description", "reason"])
    write_csv(OUT_OTHER, other, ["url", "title", "description", "reason"])
    write_csv(OUT_FAILURES, failures, ["url", "error"])

    print(f"\nWritten:")
    print(f"  {OUT_POLITICAL}  ({len(political)} rows)")
    print(f"  {OUT_OTHER}  ({len(other)} rows)")
    print(f"  {OUT_FAILURES}  ({len(failures)} rows)")

    if political:
        print("\nSample of classified-political candidates (first 10):")
        for r in political[:10]:
            print(f"  [{domain_of_url(r['url'])}] {r['title']}")
            print(f"      {r['url']}")


if __name__ == "__main__":
    main()
