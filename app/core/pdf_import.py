"""PDF'den referans çıkarımı — metinden DOI yakalar.

pypdf kuruluysa kullanılır; değilse boş döner (kullanıcı elle DOI girebilir).
"""
from __future__ import annotations
import re

_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", re.I)


def extract_doi(data: bytes, max_pages: int = 3) -> str:
    """PDF baytlarından ilk geçerli DOI'yi döner (genelde ilk sayfalardadır)."""
    try:
        import io
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        text = ""
        for page in reader.pages[:max_pages]:
            text += page.extract_text() or " "
        m = _DOI_RE.search(text)
        if m:
            # Sondaki noktalama/parantezleri temizle
            return m.group(0).rstrip(").,;")
    except Exception:
        pass
    return ""
