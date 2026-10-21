import ollama

from . import config
from .store import search


def answer(query: str, instruction: str, extra: str = "") -> str:
    """Retrieve relevant chunks for a query, then ask the model to answer from them only."""
    context = "\n\n---\n\n".join(f"[source: {h['url']}]\n{h['text']}" for h in search(query))
    res = ollama.chat(
        model=config.CHAT_MODEL,
        messages=[
            {
                "role": "system",
                "content": f"You help the user plan their day. About the user: {config.PROFILE}\n"
                "Use ONLY the provided context. For news-related tasks, organize the answer around the main topics being reported, not a list of article headlines. Treat articles as evidence or examples, and describe which sources cover each topic; point out overlap or differences only when supported by the context. Cite source URLs for relevant claims. If nothing applies, say so."
                + (f"\n\nThe user's own recent check-ins (trusted, no URL needed):\n{extra}" if extra else ""),
            },
            {"role": "user", "content": f"Context:\n{context}\n\nTask: {instruction}"},
        ],
    )
    return res["message"]["content"]
