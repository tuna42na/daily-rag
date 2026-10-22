CHAT_MODEL = "llama3.2"
EMBED_MODEL = "nomic-embed-text"
CHUNK_SIZE = 800
CHUNK_OVERLAP = 100
TOP_K = 8
INDEX_PATH = "data/index.json"
OUTPUT_DIR = "output"
# Check-in log; lives under data/, which is gitignored.
JOURNAL_PATH = "data/journal.md"
# Who you are / what you care about. Drives what the model treats as actionable.
PROFILE = "Software engineer interested in AI tooling, developer products, and startup news."
PERSONAL_CONTEXT_DIR = "personal-context"
PERSONAL_CONTEXT_CACHE = "data/personal-context.json"
PERSONAL_CONTEXT_MAX_CHARS = 40000
TASKS_PATH = "data/tasks.json"
DAILY_TASK_LIMIT = 2
MODEL_CONTEXT_TOKENS = 32768
