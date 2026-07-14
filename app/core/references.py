"""Yerleşik referans biçimlendirme + RIS/BibTeX import/export + dedup.

CSL kuruluysa csl.py devreye girer; bu modül güvenli geri-düşüş (fallback) ve
dosya formatlarını sağlar.
"""
from __future__ import annotations
import re


# ----------------------------------------------------------- yerleşik stiller
def _authors_vancouver(authors: list[str]) -> str:
    if not authors:
        return ""
    if len(authors) > 6:
        return ", ".join(authors[:6]) + ", et al"
    return ", ".join(authors)


def format_vancouver(rec: dict) -> str:
    parts = []
    auth = _authors_vancouver(rec.get("authors", []))
    if auth:
        parts.append(auth + ".")
    title = rec.get("title", "").rstrip(".")
    if title:
        parts.append(title + ".")
    journal = rec.get("iso") or rec.get("journal", "")
    cite = journal
    if rec.get("year"):
        cite += f". {rec['year']}"
    if rec.get("volume"):
        cite += f";{rec['volume']}"
    if rec.get("issue"):
        cite += f"({rec['issue']})"
    if rec.get("pages"):
        cite += f":{rec['pages']}"
    cite += "."
    parts.append(cite)
    if rec.get("doi"):
        parts.append(f"doi:{rec['doi']}.")
    return " ".join(parts)


def format_apa(rec: dict) -> str:
    auth = ", ".join(rec.get("authors", [])[:20])
    year = f"({rec.get('year','n.d.')})." if rec.get("year") else ""
    title = rec.get("title", "").rstrip(".") + "."
    journal = rec.get("journal") or rec.get("iso", "")
    tail = journal
    if rec.get("volume"):
        tail += f", {rec['volume']}"
    if rec.get("issue"):
        tail += f"({rec['issue']})"
    if rec.get("pages"):
        tail += f", {rec['pages']}"
    tail += "."
    doi = f" https://doi.org/{rec['doi']}" if rec.get("doi") else ""
    return " ".join(p for p in [auth, year, title, tail + doi] if p)


def format_harvard(rec: dict) -> str:
    auth = ", ".join(rec.get("authors", [])[:20])
    year = f"{rec.get('year','n.d.')}." if rec.get("year") else ""
    title = "'" + rec.get("title", "").rstrip(".") + "',"
    journal = rec.get("journal") or rec.get("iso", "")
    tail = journal
    if rec.get("volume"):
        tail += f", vol. {rec['volume']}"
    if rec.get("issue"):
        tail += f", no. {rec['issue']}"
    if rec.get("pages"):
        tail += f", pp. {rec['pages']}"
    tail += "."
    return " ".join(p for p in [auth, year, title, tail] if p)


_STYLES = {"vancouver": format_vancouver, "ama": format_vancouver,
           "apa": format_apa, "harvard": format_harvard}


def build_reference_list(records: list[dict], style: str = "vancouver") -> list[str]:
    fmt = _STYLES.get(style, format_vancouver)
    return [f"{i}. {fmt(r)}" for i, r in enumerate(records, 1)]


# ----------------------------------------------------------- RIS
def to_ris(records: list[dict]) -> str:
    out = []
    for r in records:
        out.append("TY  - JOUR")
        for a in r.get("authors", []):
            out.append(f"AU  - {a}")
        if r.get("title"): out.append(f"TI  - {r['title']}")
        if r.get("journal") or r.get("iso"): out.append(f"JO  - {r.get('journal') or r['iso']}")
        if r.get("year"): out.append(f"PY  - {r['year']}")
        if r.get("volume"): out.append(f"VL  - {r['volume']}")
        if r.get("issue"): out.append(f"IS  - {r['issue']}")
        if r.get("pages"): out.append(f"SP  - {r['pages']}")
        if r.get("doi"): out.append(f"DO  - {r['doi']}")
        if r.get("pmid"): out.append(f"AN  - {r['pmid']}")
        if r.get("abstract"): out.append(f"AB  - {r['abstract']}")
        out.append("ER  - ")
        out.append("")
    return "\n".join(out)


_RIS_MAP = {"TI": "title", "T1": "title", "JO": "journal", "JF": "journal", "T2": "journal",
            "PY": "year", "Y1": "year", "VL": "volume", "IS": "issue", "SP": "pages",
            "DO": "doi", "AB": "abstract", "AN": "pmid", "UR": "url", "PB": "publisher"}


def parse_ris(text: str) -> list[dict]:
    records, cur = [], None
    for line in text.splitlines():
        m = re.match(r"^([A-Z][A-Z0-9])  - (.*)$", line)
        if not m:
            if cur is not None and line.strip() and "abstract" in cur:
                cur["abstract"] += " " + line.strip()
            continue
        tag, val = m.group(1), m.group(2).strip()
        if tag == "TY":
            cur = {"type": "article-journal", "authors": []}
            records.append(cur)
        elif cur is None:
            continue
        elif tag in ("AU", "A1", "A2"):
            cur["authors"].append(val)
        elif tag == "EP" and val:
            cur["pages"] = (cur.get("pages", "") + "-" + val) if cur.get("pages") else val
        elif tag in _RIS_MAP:
            cur.setdefault(_RIS_MAP[tag], val)
    return [r for r in records if r.get("title")]


# ----------------------------------------------------------- BibTeX
def to_bibtex(records: list[dict]) -> str:
    out = []
    for i, r in enumerate(records, 1):
        first = (r.get("authors") or ["anon"])[0].split()[0].lower()
        key = f"{first}{r.get('year','')}_{i}"
        authors = " and ".join(r.get("authors", []))
        out.append(f"@article{{{key},")
        fields = [("author", authors), ("title", r.get("title", "")),
                  ("journal", r.get("journal") or r.get("iso", "")),
                  ("year", r.get("year", "")), ("volume", r.get("volume", "")),
                  ("number", r.get("issue", "")), ("pages", r.get("pages", "")),
                  ("doi", r.get("doi", ""))]
        out.append(",\n".join(f"  {k} = {{{v}}}" for k, v in fields if v))
        out.append("}\n")
    return "\n".join(out)


def parse_bibtex(text: str) -> list[dict]:
    records = []
    for entry in re.findall(r"@\w+\s*\{[^@]*\}", text, re.S):
        fields = dict(re.findall(r"(\w+)\s*=\s*[{\"]([^{}\"]*)[}\"]", entry))
        if not fields.get("title"):
            continue
        authors = [a.strip() for a in re.split(r"\s+and\s+", fields.get("author", "")) if a.strip()]
        records.append({
            "type": "article-journal", "title": fields.get("title", "").strip(),
            "authors": authors, "journal": fields.get("journal", ""),
            "year": fields.get("year", ""), "volume": fields.get("volume", ""),
            "issue": fields.get("number", ""), "pages": fields.get("pages", ""),
            "doi": fields.get("doi", ""), "abstract": fields.get("abstract", ""),
        })
    return records


# ----------------------------------------------------------- CSL-JSON (Zotero/Mendeley)
def _split_author(a: str) -> dict:
    parts = a.strip().rsplit(" ", 1)
    if len(parts) == 2 and parts[1].replace(".", "").isupper() and len(parts[1]) <= 4:
        return {"family": parts[0], "given": parts[1]}
    return {"family": a.strip()}


def to_csl_json(records: list[dict]) -> str:
    import json
    items = []
    for i, r in enumerate(records, 1):
        item = {"id": r.get("doi") or r.get("pmid") or f"ref-{i}",
                "type": r.get("type") or "article-journal",
                "title": r.get("title", ""),
                "container-title": r.get("journal") or r.get("iso", ""),
                "author": [_split_author(a) for a in r.get("authors", [])]}
        if r.get("year"):
            try:
                item["issued"] = {"date-parts": [[int(str(r["year"])[:4])]]}
            except Exception:
                pass
        for k_csl, k_rec in (("volume", "volume"), ("issue", "issue"), ("page", "pages"),
                             ("DOI", "doi"), ("PMID", "pmid"), ("abstract", "abstract")):
            if r.get(k_rec):
                item[k_csl] = str(r[k_rec])
        items.append(item)
    return json.dumps(items, ensure_ascii=False, indent=2)


# ----------------------------------------------------------- EndNote XML
def _xml_esc(s: str) -> str:
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;"))


def to_endnote_xml(records: list[dict]) -> str:
    """EndNote'un içe aktarabildiği XML formatı."""
    out = ['<?xml version="1.0" encoding="UTF-8"?>', "<xml><records>"]
    for i, r in enumerate(records, 1):
        out.append("<record>")
        out.append(f"<rec-number>{i}</rec-number>")
        out.append('<ref-type name="Journal Article">17</ref-type>')
        if r.get("authors"):
            authors = "".join(f"<author>{_xml_esc(a)}</author>" for a in r["authors"])
            out.append(f"<contributors><authors>{authors}</authors></contributors>")
        out.append("<titles>"
                   f"<title>{_xml_esc(r.get('title',''))}</title>"
                   f"<secondary-title>{_xml_esc(r.get('journal') or r.get('iso',''))}</secondary-title>"
                   "</titles>")
        out.append(f"<periodical><full-title>{_xml_esc(r.get('journal',''))}</full-title>"
                   f"<abbr-1>{_xml_esc(r.get('iso',''))}</abbr-1></periodical>")
        for tag, val in (("volume", r.get("volume")), ("number", r.get("issue")),
                         ("pages", r.get("pages"))):
            if val:
                out.append(f"<{tag}>{_xml_esc(val)}</{tag}>")
        if r.get("year"):
            out.append(f"<dates><year>{_xml_esc(r['year'])}</year></dates>")
        if r.get("doi"):
            out.append(f"<electronic-resource-num>{_xml_esc(r['doi'])}</electronic-resource-num>")
        if r.get("abstract"):
            out.append(f"<abstract>{_xml_esc(r['abstract'])}</abstract>")
        out.append("</record>")
    out.append("</records></xml>")
    return "\n".join(out)


# ----------------------------------------------------------- dedup
def _norm_title(t: str) -> str:
    return "".join(c for c in (t or "").lower() if c.isalnum())[:60]


def dedupe_key(r: dict) -> str:
    return (r.get("doi") or "").lower() or (r.get("pmid") or "") or _norm_title(r.get("title", ""))


def find_duplicates(records: list[dict]) -> list[list[dict]]:
    """Aynı DOI/PMID/normalize-başlık olan kayıtları gruplar (>1 üyeli gruplar)."""
    groups: dict[str, list[dict]] = {}
    for r in records:
        k = dedupe_key(r)
        if k:
            groups.setdefault(k, []).append(r)
    return [g for g in groups.values() if len(g) > 1]


def dedupe(records: list[dict]) -> list[dict]:
    seen, out = set(), []
    for r in records:
        k = dedupe_key(r)
        if k and k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out
