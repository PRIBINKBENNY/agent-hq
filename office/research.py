"""
Research library for the Research Lab: paper search (arXiv + OpenAlex, both free, no key), paper text,
BibTeX from metadata only, novelty checks, and the two guards that keep papers honest:
  - cite_check:    every \\cite{key} (or [@key]) in a paper must exist in references.bib, which is built ONLY from
                   API metadata (an agent cannot type a reference by hand).
  - results_check: every number in the paper's Results section must appear in experiments/results.json, which is
                   written by code that actually ran (the experimenter logs it with experiment_log).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import httpx

ARXIV = "https://export.arxiv.org/api/query"
OPENALEX = "https://api.openalex.org/works"
MAILTO = "pribinkbenny1565@gmail.com"      # OpenAlex "polite pool": faster, still free
UA = {"User-Agent": f"AgentHQ-research/1.0 (mailto:{MAILTO})"}
NS = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def _clean(s: Optional[str]) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


# ----------------------------------------------------------------------------- search
def arxiv_search(query: str, max_results: int = 10, category: str = "", newest: bool = True) -> list[dict]:
    """arXiv API. query: words (ANDed) or an arXiv query string. category e.g. cs.AI, cs.CL, cs.CV, cs.LG, cs.RO."""
    q = query.strip()
    if " AND " not in q and ":" not in q:
        q = " AND ".join(f"all:{w}" for w in re.findall(r"[\w.-]+", q)[:8])
    if category:
        q = f"({q}) AND cat:{category}"
    params = {"search_query": q, "start": 0, "max_results": int(max_results)}
    if newest:
        params.update(sortBy="submittedDate", sortOrder="descending")
    r = httpx.get(ARXIV, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for e in ET.fromstring(r.text).findall("a:entry", NS):
        aid = _clean(e.findtext("a:id", default="", namespaces=NS)).rsplit("/abs/", 1)[-1]
        out.append({"source": "arxiv", "id": aid, "title": _clean(e.findtext("a:title", default="", namespaces=NS)),
                    "authors": [_clean(a.findtext("a:name", default="", namespaces=NS)) for a in e.findall("a:author", NS)][:8],
                    "year": _clean(e.findtext("a:published", default="", namespaces=NS))[:4], "published": _clean(e.findtext("a:published", default="", namespaces=NS))[:10],
                    "abstract": _clean(e.findtext("a:summary", default="", namespaces=NS))[:1200], "url": f"https://arxiv.org/abs/{aid}",
                    "categories": [c.get("term") for c in e.findall("a:category", NS)][:4]})
    return out


def openalex_search(query: str, max_results: int = 10, since_year: int = 0, sort: str = "relevance") -> list[dict]:
    """OpenAlex (250M+ works, free). sort: relevance | cited | newest."""
    params = {"search": query, "per-page": int(max_results), "mailto": MAILTO}
    filters = ["type:article|preprint"]
    if since_year:
        filters.append(f"from_publication_date:{int(since_year)}-01-01")
    params["filter"] = ",".join(filters)
    if sort == "cited":
        params["sort"] = "cited_by_count:desc"
    elif sort == "newest":
        params["sort"] = "publication_date:desc"
    r = httpx.get(OPENALEX, params=params, headers=UA, timeout=30)
    r.raise_for_status()
    out = []
    for w in r.json().get("results", []):
        loc = w.get("primary_location") or {}; src = loc.get("source") or {}
        inv = w.get("abstract_inverted_index") or {}
        abstract = ""
        if inv:
            pos = sorted((p, t) for t, ps in inv.items() for p in ps); abstract = " ".join(t for _, t in pos)[:1200]
        out.append({"source": "openalex", "id": (w.get("id") or "").rsplit("/", 1)[-1], "doi": (w.get("doi") or "").replace("https://doi.org/", ""),
                    "title": _clean(w.get("title")), "authors": [_clean((a.get("author") or {}).get("display_name")) for a in (w.get("authorships") or [])][:8],
                    "year": str(w.get("publication_year") or ""), "venue": _clean(src.get("display_name")), "cited_by": w.get("cited_by_count", 0),
                    "abstract": abstract, "url": loc.get("landing_page_url") or w.get("doi") or "", "oa_pdf": (w.get("open_access") or {}).get("oa_url") or ""})
    return out


def paper_text(arxiv_id: str, max_chars: int = 40000) -> str:
    """Full text of an arXiv paper (its HTML rendering; falls back to the abstract page)."""
    aid = arxiv_id.strip().replace("https://arxiv.org/abs/", "").replace("arXiv:", "")
    for url in (f"https://arxiv.org/html/{aid}", f"https://arxiv.org/abs/{aid}"):
        try:
            r = httpx.get(url, headers=UA, timeout=40, follow_redirects=True)
            if r.status_code != 200:
                continue
            t = re.sub(r"<(script|style|nav|header|footer)[^>]*>.*?</\1>", " ", r.text, flags=re.S | re.I)
            t = re.sub(r"<[^>]+>", " ", t); t = re.sub(r"&[a-z]+;", " ", t); t = re.sub(r"[ \t]+", " ", t); t = re.sub(r"\n\s*\n+", "\n", t)
            if len(t.strip()) > 500:
                return t.strip()[:max_chars]
        except Exception:
            continue
    return f"could not fetch {aid}"


# ----------------------------------------------------------------------------- bibliography (metadata only)
def bib_key(p: dict) -> str:
    first = re.sub(r"[^a-z]", "", (p.get("authors") or ["anon"])[0].split()[-1].lower()) or "anon"
    word = next((w.lower() for w in re.findall(r"[A-Za-z]{4,}", p.get("title", "")) if w.lower() not in ("with", "from", "that", "this", "using", "towards", "toward")), "paper")
    return f"{first}{p.get('year', '')}{word}"


def bib_entry(p: dict) -> str:
    key = bib_key(p); authors = " and ".join(p.get("authors") or ["Anonymous"])
    if p.get("source") == "arxiv":
        return (f"@article{{{key},\n  title={{{p['title']}}},\n  author={{{authors}}},\n  journal={{arXiv preprint arXiv:{p['id']}}},\n"
                f"  year={{{p.get('year', '')}}},\n  url={{{p['url']}}}\n}}\n")
    fields = [f"  title={{{p['title']}}}", f"  author={{{authors}}}", f"  year={{{p.get('year', '')}}}"]
    if p.get("venue"):
        fields.append(f"  journal={{{p['venue']}}}")
    if p.get("doi"):
        fields.append(f"  doi={{{p['doi']}}}")
    if p.get("url"):
        fields.append(f"  url={{{p['url']}}}")
    return f"@article{{{key},\n" + ",\n".join(fields) + "\n}\n"


def bib_keys(bib_text: str) -> set[str]:
    return set(re.findall(r"@\w+\{([^,\s]+),", bib_text or ""))


def cite_check(paper_text_: str, bib_text: str) -> dict:
    """Every citation key used in the paper must exist in references.bib."""
    used = set(re.findall(r"\\cite[tp]?\{([^}]+)\}", paper_text_ or ""))
    used = {k.strip() for grp in used for k in grp.split(",")} | set(re.findall(r"\[@([\w:-]+)\]", paper_text_ or ""))
    have = bib_keys(bib_text); missing = sorted(used - have)
    return {"citations": len(used), "in_bibliography": len(used & have), "missing": missing, "ok": not missing and bool(used)}


# ----------------------------------------------------------------------------- results guard
NUM = re.compile(r"(?<![\w.])(-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)\s*(%|pp|x)?")


def _numbers(text: str) -> list[str]:
    out = []
    for m in NUM.finditer(text or ""):
        v = m.group(1).replace(",", "")
        if re.fullmatch(r"(19|20)\d\d", v) or re.fullmatch(r"\d", v):     # years and single digits are not results
            continue
        out.append(v)
    return out


def _flatten(o, acc):
    if isinstance(o, dict):
        for v in o.values():
            _flatten(v, acc)
    elif isinstance(o, (list, tuple)):
        for v in o:
            _flatten(v, acc)
    elif isinstance(o, (int, float)) and not isinstance(o, bool):
        acc.append(float(o))
    elif isinstance(o, str):
        for n in _numbers(o):
            try:
                acc.append(float(n))
            except ValueError:
                pass


def results_check(paper: str, results: dict) -> dict:
    """Numbers in the paper's Results/Experiments sections must come from results.json (logged by real runs)."""
    m = re.search(r"(?is)(^|\n)#+\s*(results|experiments|evaluation)\b(.*?)(?=\n#+\s|\Z)", paper or "")
    section = m.group(3) if m else ""
    if not section:
        m2 = re.search(r"(?is)\\section\{(results|experiments|evaluation)[^}]*\}(.*?)(?=\\section|\Z)", paper or "")
        section = m2.group(2) if m2 else ""
    claimed = _numbers(section); have: list[float] = []; _flatten(results, have)
    def backed(n: str) -> bool:
        v = float(n)
        return any(abs(v - h) < 1e-9 or (h and abs(v - round(h, len(n.split(".")[1]) if "." in n else 0)) < 1e-9) or (abs(v - h * 100) < 0.051) for h in have)
    unbacked = sorted({n for n in claimed if not backed(n)}, key=float)
    return {"numbers_claimed": len(claimed), "unbacked": unbacked, "ok": not unbacked, "has_results_section": bool(section)}


def results_fingerprint(results: dict) -> str:
    return hashlib.sha256(json.dumps(results, sort_keys=True).encode()).hexdigest()[:12]


# ----------------------------------------------------------------------------- novelty
def novelty_scan(idea: str, max_each: int = 8) -> dict:
    """Closest existing work to an idea, from both sources. The analyst judges overlap; this only gathers evidence."""
    out = {"arxiv": [], "openalex": [], "errors": []}
    try:
        out["arxiv"] = arxiv_search(idea, max_each, newest=False)
    except Exception as e:
        out["errors"].append(f"arxiv: {str(e)[:120]}")
    try:
        out["openalex"] = openalex_search(idea, max_each, since_year=int(time.strftime("%Y")) - 3)
    except Exception as e:
        out["errors"].append(f"openalex: {str(e)[:120]}")
    return out
