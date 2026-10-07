import ollama

from . import config


def embed(texts: list[str]) -> list[list[float]]:
    return ollama.embed(model=config.EMBED_MODEL, input=texts)["embeddings"]
