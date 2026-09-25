# Stackplan MVP

Stackplan converts assessment evidence from any number of modules into one
trimester pacing timeline. It describes workload timing, importance, weekly
pressure, overlaps, clusters, and incomplete evidence. It does not create study
plans or recommend how a student should spend their time.

## Flow

```text
Frontend Demo
  -> IO Manager validates and normalizes all modules
  -> AI Manager extracts assessment facts and uncertainty
  -> Logic Manager calculates importance, proximity, ranking, and pressure
  -> Data Manager stores input, extraction, and the final result
  -> Frontend renders the pacing timeline
```

`src/main.py` remains the orchestration layer. The former one-module Python
entry point is retained for compatibility, while the frontend uses the new
`{"modules": [...]}` request.

## Deterministic calculations

- Academic importance = assessment weightage × module credit units.
- Weeks remaining = due week − current trimester week.
- Proximity = 0 for past assessments; otherwise
  `1 / max(weeks_remaining, 1)`.
- Relative score = academic importance × proximity.
- Every module is validated independently: effective assessment weights must
  total 100%. Collective recurring weights count once; genuine per-occurrence
  weights count once per occurrence.
- Weekly pressure score = five points per assessment occurrence + the sum of
  academic importance divided by ten.
- Pressure labels are `low` (<15), `moderate` (<35), `high` (<65), and
  `very_high` (65+).

Recurring assessments contribute to every known occurrence week. Multi-week
assessments contribute throughout their known range. Missing weightages, credit
units, or weeks remain visible as comments/checklist items rather than causing
the whole pipeline to fail.

Each module is extracted in its own model request. Up to five module requests run
in parallel by default (`AI_MAX_PARALLEL_MODULES`), keeping evidence contexts
small and reducing multi-module latency. A recurring participation weight marked
as `total` is spread across its occurrence weeks for pressure calculations; the
full percentage is never counted once per week.

### Code map

- `src/ai_manager.py`: active multi-module extraction flow. Functions follow the
  call order: public API → per-module extraction → evidence preparation → model
  contract → response normalization → small helpers.
- `process`: fans modules out into independent parallel requests and restores
  their original order.
- `_extract_module`: runs one module request, handles fallback models, and keeps
  failures isolated to that module.
- `_build_pacing_prompt`: reads only that module's non-image evidence, then asks
  the prompt module to construct the request.
- `_call_pacing_model`: performs the structured Qwen request with model thinking
  disabled and a bounded output size.
- `_pacing_schema`: defines the JSON contract, including recurring weight scope.
- `_normalize_module_result`: validates model field types, numeric bounds, and
  recurrence structure without module- or test-case-specific lookup tables.
- `validate_ai_output`: verifies module references and preserves a compact set of
  material warnings before deterministic logic runs.
- `src/system_prompts.py`: contains all model instructions and user-prompt
  builders. Editing prompt policy no longer requires navigating transport code.
- `src/ai_support.py`: contains shared multimodal-message, JSON, model-route, and
  safe-error helpers.
- `src/legacy_extraction.py`: isolates the former one-module AI schema and flow.
- `src/logic_manager.py`: owns the trimester calendar data and every
  deterministic calculation.

`ai_manager.extract_assessments` remains as a small compatibility proxy, so the
former one-module API and tests still work without cluttering the active flow.

The calendar has one source of truth in `src/logic_manager.py`. The current
configuration is SIT AY2026/27 Trimester 1 (31 August–6 December 2026), including
recess in Week 7 and final assessment in Week 14. Its generated data is injected
into the AI prompt; the dates are not duplicated in prompt text.

## Run

Copy `.env.example` to `.env` and provide `DASHSCOPE_API_KEY`.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python frontend-demo/app.py
```

- Frontend: http://127.0.0.1:5050
- Extraction endpoint: http://127.0.0.1:5050/api/extractions
- Health: http://127.0.0.1:5050/health

The frontend accepts images, PDF, DOCX, and simple text-based files. Uploads
exist only for the duration of one request. The Flask app calls `src/main.py`
directly and runs on the host; it is not built into the Docker Compose stack.

Run `docker compose up -d db` and set
`DATABASE_URL=postgresql://stackplan:stackplan_dev@127.0.0.1:5433/stackplan`
before starting Flask. Docker Compose starts only PostgreSQL; Flask always runs
independently on the host. There is no local JSON persistence fallback.

The Compose database is intentionally disposable: PostgreSQL stores its data in
container memory rather than a named or host volume. `docker compose restart db`
or `docker compose down` clears the database so the next start is a clean test
run. This reset applies when Flask is using the `DATABASE_URL` above. If
`DATABASE_URL` is unset, storage is unavailable rather than silently switching
to another persistent data source.

## Test

```sh
python -m pytest -q
```
