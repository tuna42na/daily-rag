import json
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .chunk import chunk
from .embed import embed
from .fetch import fetch_text
from .store import load, save


def ingest() -> None:
    sources = json.loads(Path("sources.json").read_text())
    records = load()
    for s in sources:
        try:
            pieces = chunk(fetch_text(s["url"], s.get("selector")), config.CHUNK_SIZE, config.CHUNK_OVERLAP)
            embeddings = embed(pieces)
        except Exception as e:
            print(f"Skipping {s['url']}: {e}")
            continue
        now = datetime.now(timezone.utc).isoformat()
        fresh = [{"text": t, "embedding": e, "url": s["url"], "fetched_at": now} for t, e in zip(pieces, embeddings)]
        records = [r for r in records if r["url"] != s["url"]] + fresh
        print(f"{s['url']}: {len(fresh)} chunks")
    save(records)


if __name__ == "__main__":
    ingest()
