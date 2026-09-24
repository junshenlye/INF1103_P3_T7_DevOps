# Stackplan MVP

Stackplan reads one module's assessment screenshots, extracts every visible
assessment, and turns valid events into a compact weekly preparation timetable.

The current milestone deliberately handles one module at a time. Multi-module
competition is the next iteration.

## Procedural flow

```text
Input
  -> I/O Manager validates user data
  -> AI Manager extracts structured events
  -> Logic Manager assigns status, priority, and preparation dates
  -> Data Manager validates and saves the finished records
Output
```

Each stage receives ordinary dictionaries as arguments and returns a result to
the next stage. Project-owned Python defines no classes and keeps no mutable
application state at module level.

## Small file map

```text
src/
  io_manager.py       input/output and record validation
  ai_manager.py       Nemotron/OpenRouter extraction
  logic_manager.py    deterministic status and timetable rules
  data_manager.py     JSON/PostgreSQL persistence and history
  main.py             passes results between managers; CLI entry point

helpers/api_server.py thin Docker HTTP adapter and temporary progress files
frontend-demo/        host-run presentation only
```

`data_manager.py` uses PostgreSQL when Docker supplies `DATABASE_URL`. The CLI
continues to use JSON, so the graded procedural core does not require Docker.
Those local JSON files are created under the Git-ignored `data/` directory.

## Run

Copy `.env.example` to `.env` and provide `OPENROUTER_API_KEY`.

Start the main program and temporary database:

```sh
docker compose up --build
```

Start the editable frontend outside Docker in a second terminal:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python frontend-demo/app.py
```

Addresses:

- Frontend: http://127.0.0.1:5050
- Docker API: http://127.0.0.1:8000
- Health check: http://127.0.0.1:8000/health
- PostgreSQL: `127.0.0.1:5433`

PostgreSQL uses Docker `tmpfs`. `docker compose down` clears the current data.
Uploaded images and extraction progress files are also temporary.

## Current proof of concept

1. Enter one module code and its credits.
2. Drop all screenshots for that module into one request.
3. Watch the extraction stages and bounded AI retries.
4. Review the extracted assessments.
5. See READY events as small coloured blocks in a weekly strip.

Missing deadlines or weights remain visible for correction but stay out of the
timetable. The saved record shape remains the frozen assignment contract.

Automated test files are intentionally kept local during this early MVP and are
ignored by Git to keep the shared repository focused on the handoff code.
