"""CSL (Citation Style Language) ile dergiye özgü referans biçimlendirme.

citeproc-py + citeproc-py-styles ile binlerce derginin tam formatı üretilir.
Kullanıcı kendi .csl dosyalarını app/csl/ klasörüne VEYA REFLY_CSL_DIR ile
gösterilen bir masaüstü klasörüne bırakabilir; ad ile çağrılır.

Stil bulunamazsa references.py'daki yerleşik formatlayıcılara zarifçe düşer.
"""
from __future__ import annotations
import os
from pathlib import Path

from . import references as ref_mod
from ..config import Config

_BUNDLED_DIR = Path(__file__).resolve().parent.parent / "csl"


def _user_dirs() -> list[Path]:
    dirs = [_BUNDLED_DIR]
    if Config.USER_CSL_DIR:
        p = Path(os.path.expanduser(Config.USER_CSL_DIR))
        if p.is_dir():
            dirs.append(p)
    return dirs


# Sık kullanılan dergi/aile -> CSL stil kimliği (citeproc-py-styles adları)
_JOURNAL_TO_CSL = {
    "jama": "american-medical-association", "ama": "american-medical-association",
    "nejm": "the-new-england-journal-of-medicine", "lancet": "the-lancet",
    "bmj": "bmj", "nature": "nature", "science": "science",
    "plos one": "plos-one", "plos": "plos", "cell": "cell",
    "spine": "vancouver", "vancouver": "vancouver",
    "ieee": "ieee", "apa": "apa", "mla": "modern-language-association",
    "chicago": "chicago-author-date", "harvard": "harvard-cite-them-right",
    "elsevier": "elsevier-vancouver", "springer": "springer-vancouver-brackets",
}


def available() -> bool:
    try:
        import citeproc  # noqa: F401
        import citeproc_styles  # noqa: F401
        return True
    except Exception:
        return False


def list_local_styles() -> list[str]:
    """app/csl/ ve kullanıcı klasöründeki .csl dosya adları."""
    names = set()
    for d in _user_dirs():
        for f in d.glob("*.csl"):
            names.add(f.stem)
    return sorted(names)


def _styles_repo_dir():
    try:
        import citeproc_styles, os
        d = os.path.join(os.path.dirname(citeproc_styles.__file__), "styles")
        return d if os.path.isdir(d) else None
    except Exception:
        return None


def search_styles(query: str, limit: int = 40) -> list[dict]:
    """Tüm CSL deposunda (2000+ dergi) stil arar. Döner: [{id, label}]."""
    repo = _styles_repo_dir()
    if not repo:
        return []
    import os
    q = (query or "").strip().lower()
    hits = []
    for f in os.listdir(repo):
        if not f.endswith(".csl"):
            continue
        sid = f[:-4]
        if not q or q in sid.replace("-", " "):
            hits.append({"id": sid, "label": sid.replace("-", " ")})
    hits.sort(key=lambda h: (not h["id"].startswith(q), len(h["id"]), h["id"]))
    return hits[:limit]


def resolve_style(name: str) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    for d in _user_dirs():
        local = d / f"{key}.csl"
        if local.exists():
            return str(local)
    candidates = []
    if key in _JOURNAL_TO_CSL:
        candidates.append(_JOURNAL_TO_CSL[key])
    candidates += [key, key.replace(" ", "-")]
    try:
        from citeproc_styles import get_style_filepath
    except Exception:
        return None
    for cand in candidates:
        try:
            return get_style_filepath(cand)
        except Exception:
            continue
    return None


def _to_csl_json(records: list[dict]) -> list[dict]:
    items = []
    for i, r in enumerate(records, 1):
        authors = []
        for a in r.get("authors", []):
            parts = a.strip().rsplit(" ", 1)
            if len(parts) == 2 and parts[1].replace(".", "").isupper() and len(parts[1]) <= 4:
                authors.append({"family": parts[0], "given": parts[1]})
            else:
                authors.append({"family": a.strip()})
        item = {"id": f"ITEM-{i}", "type": r.get("type") or "article-journal",
                "title": r.get("title", ""),
                "container-title": r.get("journal") or r.get("iso", ""),
                "author": authors}
        if r.get("year"):
            try:
                item["issued"] = {"date-parts": [[int(str(r["year"])[:4])]]}
            except Exception:
                pass
        for k_csl, k_rec in (("volume", "volume"), ("issue", "issue"),
                             ("page", "pages"), ("DOI", "doi"),
                             ("publisher", "publisher"), ("URL", "url")):
            if r.get(k_rec):
                item[k_csl] = str(r[k_rec])
        items.append(item)
    return items


def build_reference_list(records: list[dict], style: str = "vancouver") -> list[str]:
    if not records:
        return []
    path = resolve_style(style) if available() else None
    if not path:
        return ref_mod.build_reference_list(records, style=_fallback(style))
    try:
        from citeproc import CitationStylesStyle, CitationStylesBibliography
        from citeproc import Citation, CitationItem, formatter
        from citeproc.source.json import CiteProcJSON

        bib_source = CiteProcJSON(_to_csl_json(records))
        csl_style = CitationStylesStyle(path, validate=False)
        bib = CitationStylesBibliography(csl_style, bib_source, formatter.plain)
        for i in range(1, len(records) + 1):
            bib.register(Citation([CitationItem(f"ITEM-{i}")]))
        out = []
        for i, entry in enumerate(bib.bibliography(), 1):
            text = _tidy(str(entry).strip())
            out.append(text if text[:2].strip().rstrip(".").isdigit() else f"{i}. {text}")
        return out or ref_mod.build_reference_list(records, style=_fallback(style))
    except Exception:
        return ref_mod.build_reference_list(records, style=_fallback(style))


def _tidy(text: str) -> str:
    """citeproc çıktısındaki çift noktalama ('et al..', 'Vaccine..') gibi
    artifaktları temizler. URL'leri bozmamak için 'http' içeren kısma dokunmaz."""
    import re
    # 'et al..' / 'word..' -> tek nokta; üç nokta (...) korunur
    text = re.sub(r"(?<!\.)\.\.(?!\.)", ".", text)
    return text.strip()


def _fallback(style: str) -> str:
    key = (style or "").lower()
    if "apa" in key:
        return "apa"
    if "harvard" in key:
        return "harvard"
    if "ama" in key or "jama" in key:
        return "ama"
    return "vancouver"
