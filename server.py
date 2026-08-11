import os
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from fastmcp import FastMCP

mcp = FastMCP("PubMed MCP")
BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _common() -> dict[str, str]:
    p = {"tool": "pubmed-mcp-remote", "email": os.getenv("NCBI_EMAIL", "")}
    key = os.getenv("NCBI_API_KEY")
    if key:
        p["api_key"] = key
    return p


async def _get(endpoint: str, params: dict[str, Any]) -> str:
    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        r = await client.get(f"{BASE}/{endpoint}", params={**_common(), **params})
        r.raise_for_status()
        return r.text


def _text(node, path: str) -> str:
    x = node.find(path)
    return "" if x is None else "".join(x.itertext()).strip()


@mcp.tool()
async def search_pubmed(query: str, max_results: int = 10, sort: str = "pub_date") -> dict:
    """Search PubMed and return PMIDs for a query."""
    xml = await _get("esearch.fcgi", {
        "db": "pubmed", "term": query, "retmode": "xml",
        "retmax": max(1, min(max_results, 100)), "sort": sort,
    })
    root = ET.fromstring(xml)
    return {
        "query": query,
        "count": int(root.findtext("Count", "0")),
        "pmids": [x.text for x in root.findall(".//IdList/Id") if x.text],
    }


@mcp.tool()
async def fetch_pubmed(pmids: list[str]) -> list[dict]:
    """Fetch PubMed citation details and abstracts for one or more PMIDs."""
    if not pmids:
        return []
    xml = await _get("efetch.fcgi", {
        "db": "pubmed", "id": ",".join(pmids[:100]), "retmode": "xml"
    })
    root = ET.fromstring(xml)
    out = []
    for a in root.findall(".//PubmedArticle"):
        med = a.find("MedlineCitation")
        art = med.find("Article") if med is not None else None
        if med is None or art is None:
            continue
        abstract_parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.attrib.get("Label")
            txt = "".join(ab.itertext()).strip()
            abstract_parts.append(f"{label}: {txt}" if label else txt)
        authors = []
        for au in art.findall(".//AuthorList/Author"):
            name = " ".join(filter(None, [au.findtext("ForeName"), au.findtext("LastName")]))
            if name:
                authors.append(name)
        doi = ""
        for aid in a.findall(".//ArticleIdList/ArticleId"):
            if aid.attrib.get("IdType") == "doi":
                doi = aid.text or ""
        pmid = med.findtext("PMID", "")
        out.append({
            "pmid": pmid,
            "title": _text(art, "ArticleTitle"),
            "journal": _text(art, "Journal/Title"),
            "year": art.findtext("Journal/JournalIssue/PubDate/Year", "") or art.findtext("Journal/JournalIssue/PubDate/MedlineDate", ""),
            "authors": authors,
            "abstract": "\n".join(abstract_parts),
            "doi": doi,
            "pubmed_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
        })
    return out


@mcp.tool()
async def search_and_fetch(query: str, max_results: int = 10) -> list[dict]:
    """Search PubMed then fetch citation details and abstracts."""
    result = await search_pubmed(query, max_results=max_results)
    return await fetch_pubmed(result["pmids"])


@mcp.tool()
async def fetch_pmc_full_text(pmcid: str) -> str:
    """Fetch XML full text for an open-access PMC article by PMCID."""
    return await _get("efetch.fcgi", {"db": "pmc", "id": pmcid, "retmode": "xml"})


if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    mcp.run(transport="http", host="0.0.0.0", port=port, path="/mcp")
