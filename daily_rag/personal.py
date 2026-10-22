import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, TypeAdapter
from pypdf import PdfReader

from . import config


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str
    fingerprint: str
    text: str


def refresh() -> list[Document]:
    """Refresh the local snapshot; changed/deleted files replace/remove old content."""
    root = Path(config.PERSONAL_CONTEXT_DIR)
    cache = Path(config.PERSONAL_CONTEXT_CACHE)
    adapter = TypeAdapter(list[Document])
    previous = adapter.validate_json(cache.read_text()) if cache.exists() else []
    by_source = {doc.source: doc for doc in previous}
    documents = []
    if root.exists() and not root.is_dir():
        raise ValueError(f"Personal context is not a directory: {root}")
    for path in sorted(root.rglob("*")) if root.exists() else []:
        if any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Personal context symlinks are not supported: {path}")
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt", ".pdf"}:
            continue
        source = path.as_posix()
        fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
        old = by_source.get(source)
        if old and old.fingerprint == fingerprint:
            documents.append(old)
            continue
        if path.suffix.lower() == ".pdf":
            text = "\n\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
        else:
            text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ValueError(f"No readable text in {path}; scanned PDFs need OCR first.")
        documents.append(Document(source=source, fingerprint=fingerprint, text=text.strip()))
    total = sum(len(doc.text) for doc in documents)
    if total > config.PERSONAL_CONTEXT_MAX_CHARS:
        raise ValueError(
            f"Personal context has {total} characters; limit is "
            f"{config.PERSONAL_CONTEXT_MAX_CHARS}. Shorten the documents or raise the limit."
        )
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([doc.model_dump() for doc in documents]), encoding="utf-8")
    return documents


def format_context(documents: list[Document]) -> str:
    return "\n\n---\n\n".join(
        f"[source: {doc.source}; revision: {doc.fingerprint[:12]}]\n{doc.text}"
        for doc in documents
    )
