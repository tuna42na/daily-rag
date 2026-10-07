def chunk(text: str, size: int, overlap: int) -> list[str]:
    """Split text into overlapping fixed-size chunks."""
    chunks = []
    for i in range(0, len(text), size - overlap):
        chunks.append(text[i : i + size])
        if i + size >= len(text):
            break
    return chunks
