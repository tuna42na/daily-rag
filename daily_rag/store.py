import json
import math
from pathlib import Path

from . import config
from .embed import embed


def load() -> list[dict]:
    p = Path(config.INDEX_PATH)
    return json.loads(p.read_text()) if p.exists() else []


def save(records: list[dict]) -> None:
    p = Path(config.INDEX_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(records))


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


def search(query: str, top_k: int = config.TOP_K) -> list[dict]:
    """Return the top_k records most similar to the query."""
    q = embed([query])[0]
    return sorted(load(), key=lambda r: _cosine(q, r["embedding"]), reverse=True)[:top_k]
