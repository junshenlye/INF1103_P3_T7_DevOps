# Stackplan MVP

Stackplan turns module assessment screenshots into one credit-aware student
schedule. The user supplies the module code and credits because those details
are commonly missing from assessment snapshots. Nemotron extracts the events;
the procedural core validates, prioritises, stores, and schedules them.

## Development layout

```text
Host browser
    |
    v
Frontend on 127.0.0.1:5050          (outside Docker)
    |
    v
HTTP API on 127.0.0.1:8000          (Docker: app)
    |
    v
Procedural core in src/             (input -> process -> output)
    |
    v
PostgreSQL on 127.0.0.1:5433        (Docker: db, temporary data)
```

Docker contains only the main API and PostgreSQL. The frontend runs directly
on the host so teammates can edit and refresh it without rebuilding an image.

The current PostgreSQL data directory is a Docker `tmpfs`. Running
`docker compose down` removes the database state. This is intentional while the
schema and product behaviour are still changing.

## Start the MVP

Create `.env` from `.env.example` and add the OpenRouter API key. Never commit
that file.

Start the API and temporary database:

```sh
docker compose up --build
```

Readable Docker addresses:

- API: http://127.0.0.1:8000
- API health: http://127.0.0.1:8000/health
- PostgreSQL: `127.0.0.1:5433`

In a second terminal, start the frontend outside Docker:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python frontend-demo/app.py
```

Open http://127.0.0.1:5050.

## Processing flow

The project follows an IPO-style procedural flow:

1. **Input** — `io_manager.py` validates module context, prompts, and images.
2. **Process** — `ai_manager.py` extracts events and `logic_manager.py` derives
   status, priority, and schedule blocks.
3. **Output** — `storage_manager.py` selects JSON for local CLI work or
   PostgreSQL for the Docker API.

The AI may return several assessments from one module pack. Missing values are
preserved for review rather than causing the entire import to be discarded.
The frontend displays live elapsed time, AI attempt count, validation, saving,
and scheduling stages so a slow free-model response does not appear frozen.

## Folder responsibilities

- `src/` — graded procedural business logic.
- `helpers/` — development adapters: HTTP API and short-lived progress state.
- `frontend-demo/` — host-run presentation only; no scheduling rules.
- `tests/` — a small MVP safety suite, not a frozen specification.
- `data/` — JSON fallback for CLI/local experiments; Docker uses PostgreSQL.

Project-owned Python contains no classes. Terminal `print()` calls remain
confined to `src/io_manager.py`.

## Frozen assessment record

PostgreSQL stores the same record shape used by the original JSON MVP:

```json
{
  "record_id": "string",
  "module": "string",
  "assessment_type": "string",
  "deadline": "YYYY-MM-DD or null",
  "weightage": "number or null",
  "priority": "HIGH | MEDIUM | LOW | null",
  "status": "READY | INCOMPLETE | NEEDS_REVIEW | CONFLICT | CONSTRAINED",
  "missing_fields": [],
  "issues": [],
  "revision": 1
}
```

## Checks

```sh
python -m pytest -q
```

The reduced suite covers the architecture constraints, extraction boundary,
atomic storage, schedule rules, host frontend/API hand-off, and Docker shape.
