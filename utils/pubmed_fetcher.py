"""
PubMed Fetcher Utility

Queries NCBI E-utilities to retrieve recent abstracts for a gene + context.
Used by Stage 2.5 (Literature Analyst) to ground protocol generation in real papers.

Two-step NCBI workflow:
  1. esearch — get PMIDs matching the query
  2. efetch   — retrieve full abstracts for those PMIDs (XML)
"""

from __future__ import annotations

import json
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import quote_plus
from urllib.request import urlopen

# NCBI E-utilities base URL
_EUTILS_BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Default cap — keep low to avoid large context in protocol generator
DEFAULT_MAX_PAPERS = 4


def fetch_papers(
    gene: str,
    experimental_context: str,
    max_papers: int = DEFAULT_MAX_PAPERS,
) -> list[dict]:
    """
    Search PubMed and return paper dicts for the literature analyst.

    Args:
        gene:                   HGNC gene symbol (e.g. "TP53").
        experimental_context:   Free-text context (e.g. "apoptosis HeLa cisplatin").
        max_papers:             Maximum number of papers to return.

    Returns:
        List of dicts with keys: title, journal, year, abstract.
        Empty list on any network failure (never blocks the pipeline).
    """
    api_key = os.environ.get("PUBMED_API_KEY", "")

    query = _build_query(gene, experimental_context)
    pmids = _esearch(query, max_papers, api_key)
    if not pmids:
        return []

    papers = _efetch(pmids, api_key)
    return papers


# ── Internal helpers ───────────────────────────────────────────────────────

def _build_query(gene: str, context: str) -> str:
    """Build a focused PubMed query for CRISPR knockout of this gene."""
    # Keep focused on CRISPR methodology for this gene — context adds one term max
    context_words = [w for w in context.split() if len(w) > 5]
    context_term = f" AND {context_words[0]}" if context_words else ""
    return f"{gene}[Title/Abstract] AND CRISPR[Title/Abstract] AND knockout[Title/Abstract]{context_term}"


def _esearch(query: str, max_results: int, api_key: str) -> list[str]:
    """Return a list of PMIDs for the query."""
    params = (
        f"db=pubmed"
        f"&term={quote_plus(query)}"
        f"&retmax={max_results}"
        f"&sort=relevance"
        f"&retmode=json"
    )
    if api_key:
        params += f"&api_key={api_key}"

    url = f"{_EUTILS_BASE}/esearch.fcgi?{params}"
    try:
        with urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return data.get("esearchresult", {}).get("idlist", [])
    except Exception:
        return []


def _efetch(pmids: list[str], api_key: str) -> list[dict]:
    """Fetch and parse abstracts for the given PMIDs."""
    id_str = ",".join(pmids)
    params = (
        f"db=pubmed"
        f"&id={id_str}"
        f"&rettype=abstract"
        f"&retmode=xml"
    )
    if api_key:
        params += f"&api_key={api_key}"

    url = f"{_EUTILS_BASE}/efetch.fcgi?{params}"
    try:
        with urlopen(url, timeout=15) as resp:
            xml_bytes = resp.read()
    except Exception:
        return []

    return _parse_pubmed_xml(xml_bytes)


def _parse_pubmed_xml(xml_bytes: bytes) -> list[dict]:
    """Parse PubMed XML into a list of paper dicts."""
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return []

    papers = []
    for article in root.findall(".//PubmedArticle"):
        title   = _get_text(article, ".//ArticleTitle")
        journal = _get_text(article, ".//Journal/Title")
        year    = (
            _get_text(article, ".//PubDate/Year")
            or _get_text(article, ".//PubDate/MedlineDate")[:4]
        )
        # AbstractText may have multiple sections — join them
        abstract_parts = [
            (node.text or "").strip()
            for node in article.findall(".//AbstractText")
        ]
        abstract = " ".join(p for p in abstract_parts if p)

        pmid = _get_text(article, ".//MedlineCitation/PMID")
        authors = _extract_authors(article)

        if title and abstract:
            papers.append({
                "title":    title,
                "journal":  journal or "Unknown Journal",
                "year":     year or "Unknown",
                "abstract": abstract,
                "pmid":     pmid,
                "authors":  authors,
            })

    return papers


def _extract_authors(article: ET.Element) -> str:
    """Return 'Last et al.' or 'Last & Last' for ≤2 authors."""
    author_nodes = article.findall(".//AuthorList/Author")
    last_names = [
        _get_text(a, "LastName")
        for a in author_nodes
        if _get_text(a, "LastName")
    ]
    if not last_names:
        return ""
    if len(last_names) == 1:
        return last_names[0]
    if len(last_names) == 2:
        return f"{last_names[0]} & {last_names[1]}"
    return f"{last_names[0]} et al."


def _get_text(element: ET.Element, path: str) -> str:
    """Return stripped text at XPath, or empty string if missing."""
    node = element.find(path)
    if node is None or node.text is None:
        return ""
    return node.text.strip()


# ── Smoke test ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")

    print("Fetching TP53 CRISPR papers from PubMed…")
    results = fetch_papers("TP53", "apoptosis cisplatin HeLa", max_papers=3)
    if results:
        for i, p in enumerate(results, 1):
            print(f"\n[{i}] {p['title']}")
            print(f"     {p['journal']} ({p['year']})")
            print(f"     {p['abstract'][:200]}…")
    else:
        print("No results (check network / API key).")
