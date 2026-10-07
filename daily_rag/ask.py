import sys

from .generate import answer

q = " ".join(sys.argv[1:])
if not q:
    sys.exit('Usage: python -m daily_rag.ask "your question"')
print(answer(q, q))
