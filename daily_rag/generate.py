import ollama

from . import config
from .store import search


def answer(query: str, instruction: str) -> str:
    """Retrieve relevant chunks for a query, then ask the model to answer from them only."""
    context = "\n\n---\n\n".join(f"[source: {h['url']}]\n{h['text']}" for h in search(query))
    res = ollama.chat(
        model=config.CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": f"You help the user plan their day. About the user: {config.PROFILE}\n"
                "Use ONLY the provided context. Cite the source URL for each item. If nothing applies, say so.",
            },
            {"role": "user", "content": f"Context:\n{context}\n\nTask: {instruction}"},
        ],
    )
    return res["message"]["content"]
