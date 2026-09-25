# Stackplan MVP

Stackplan reads one module's assessment screenshots, extracts every visible
assessment, and places valid events into a compact Week 1, Week 2, Week 3…
timetable. This MVP deliberately analyses one module at a time.

## Procedural flow

```text
Input
  -> I/O Manager validates user data
  -> AI Manager extracts structured events (Qwen Plus, then Flash fallback)
  -> Logic Manager builds the timetable and missing-information checklist
  -> Data Manager saves the finished plan
Output
```

Each stage receives ordinary dictionaries as arguments and returns a result to
the next stage. Project-owned Python defines no classes and keeps no mutable
application state at module level.

## Small file map

```text
src/
  io_manager.py       request validation
  ai_manager.py       Qwen extraction through Alibaba Model Studio
  logic_manager.py    deterministic status and timetable rules
  data_manager.py     PostgreSQL persistence
  main.py             passes results between managers

helpers/api_server.py thin Docker HTTP adapter
frontend-demo/        host-run presentation only
```

The core has one clear step per manager and one PostgreSQL table containing only
the latest single-module plan. It deliberately has no CLI mode, JSON
fallback, revision history, correction workflow, or multi-module selection.

## Run

Copy `.env.example` to `.env` and provide `DASHSCOPE_API_KEY`.

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
Uploaded images exist only while one request is being processed.

The AI manager logs the extraction workflow at `INFO` level, including model
attempts, fallback routing, returned assessment counts, and completion. Failures
are logged without exposing prompts, images, API keys, or raw model output.

## Current proof of concept

1. Enter one module code.
2. Drop all screenshots for that module into one request.
3. Wait while Qwen Plus extracts the facts or Qwen Flash takes over.
4. Receive the read-only Week 1…N timetable.
5. Use the AI checklist to find evidence missing from unscheduled items.

Deadlines use only `Week N` (for example, `Week 3`). Missing or ambiguous facts
do not stop the request. Safe events still appear in the timetable, while
unclear items become a short checklist; there is no review form or block editor.
Multiple events in the same week stack vertically, with higher priority lower in
the stack.

Automated test files are intentionally kept local during this early MVP and are
ignored by Git to keep the shared repository focused on the handoff code.
