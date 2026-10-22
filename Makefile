PYTHON ?= python3

.PHONY: help config check-config install test daily ingest ask tasks

help:
	@printf '%s\n' \
		'config   Create local configuration from the example (never overwrites)' \
		'install  Install the project in editable mode' \
		'test     Run the test suite' \
		'daily    Generate the daily digest (DAILY_ARGS="--no-ingest")' \
		'ingest   Refresh the source index' \
		'ask      Ask a question (QUESTION="your question")' \
		'tasks    List or update tasks (TASK_ARGS="list")'

config:
	@if [ -e daily_rag/config.py ] || [ -L daily_rag/config.py ]; then \
		printf '%s\n' 'Keeping existing daily_rag/config.py'; \
	else \
		cp -n daily_rag/config.example.py daily_rag/config.py && \
		printf '%s\n' 'Created daily_rag/config.py; review its models, paths, and profile before running.'; \
	fi

check-config:
	@if [ ! -f daily_rag/config.py ]; then \
		printf '%s\n' 'Missing daily_rag/config.py. Run "make config", then edit it for your models, paths, and profile.' >&2; \
		exit 1; \
	fi

install:
	$(PYTHON) -m pip install -e .

test: check-config
	$(PYTHON) -m unittest discover -s tests

daily: check-config
	$(PYTHON) -m daily_rag.daily $(DAILY_ARGS)

ingest: check-config
	$(PYTHON) -m daily_rag.ingest

ask: check-config
	$(PYTHON) -m daily_rag.ask "$(QUESTION)"

tasks: check-config
	$(PYTHON) -m daily_rag.tasks $(TASK_ARGS)
