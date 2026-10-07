import re

import httpx
from bs4 import BeautifulSoup


def fetch_text(url: str, selector: str | None = None) -> str:
    """Download a page and return cleaned plain text."""
    res = httpx.get(url, headers={"User-Agent": "daily-rag/0.1"}, follow_redirects=True, timeout=30)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        tag.decompose()
    nodes = soup.select(selector) if selector else [soup.body or soup]
    text = "\n".join(n.get_text(" ") for n in nodes)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n", text).strip()
