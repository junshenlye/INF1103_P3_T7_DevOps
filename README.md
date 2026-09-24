# INF1103_P3_T7_DevOps

1. Problem Statement and Target Users
o What real world problem does your application aim to solve?

Students often struggle to manage multiple assignments, quizzes, and exams across different modules, especially when deadlines overlap. Our application provides a consolidated academic schedule and helps students prioritize tasks based on deadlines and assessment weightage, allowing them to make better trade-offs between competing academic commitments. 

o Who are the intended users of the application?

SIT students managing multiple modules and graded assessments.

2. User Inputs
o What information or data will users provide to the system?
Users provide:

Assessment details: module, assessment type, weightage, and deadline.
Module context: module credits, used to calculate credit-weighted workload.
Study preferences: personalized rules for prioritization, such as additional revision time before quizzes or buffer periods before final exams.

These inputs allow the system to generate a priority timeline tailored to each student’s workload and study habits.

3. Use of AI
o How will AI be utilized within the application?

A multimodal AI model will extract assessment information from uploaded module schedules and combine it with the user's study preferences. The model will evaluate competing assessments based on factors such as deadline, weightage, and required preparation time to determine their relative priority.

o What outputs, insights, or recommendations will the AI generate from the user inputs?

The AI will generate a rolling priority timeline containing upcoming assessments and recommended preparation periods.

Each event will include:

Module and assessment type
Deadline
Assessment weightage
Recommended preparation period
Priority level

When multiple assessments occur within the same period, they will be displayed as stacked blocks to show competing workload and priority.


4. Business Rules
o What business rules, validations, or decision-making logic will be applied to the AI-generated outputs?

The AI output must follow a predefined JSON structure before it can be accepted by the application.

Each timeline block must contain required fields such as:

Module
Assessment category
Deadline
Weightage
Priority
Start and end period
Block size

The application will validate that:

Required fields are present.
Dates and weightages are valid.
Events are positioned in the correct week.
Higher-weighted or more urgent assessments receive appropriate priority.
Timeline blocks follow the required category and size format.

Invalid AI outputs will be rejected and regenerated before being displayed to the user.

Git Repository:
https://github.com/junshenlye/INF1103_P3_T7_DevOps 

## MVP architecture

The assessed application core lives in `src/` and is entirely procedural. The
mandatory flow is:

```text
User / file -> io_manager -> ai_manager -> logic_manager -> data_manager
```

- `src/io_manager.py` owns terminal input, validation, formatting, and all
  user-facing output calls.
- `src/ai_manager.py` owns prompt construction, OpenRouter communication,
  response parsing, and AI schema validation.
- `src/logic_manager.py` owns deterministic assessment and priority rules.
- `src/data_manager.py` owns JSON persistence and record queries.
- `src/main.py` orchestrates those functions and remains the CLI entry point.
- `src/contracts.py` is the single source of truth for the shared record shape.

The existing `frontend-demo/` is optional visualisation support. It must not
contain assessment, scheduling, AI, or persistence rules.

Project-owned Python code must not define classes. Third-party libraries may
use classes internally.

## Frozen assessment record contract

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
  "issues": [
    {
      "type": "string",
      "field": "string or null",
      "severity": "info | warning | error",
      "feedback": "string"
    }
  ],
  "revision": 1
}
```

Changing this contract requires an explicit review of affected modules and
stored-data migration impact before implementation.

## Run the procedural application

Requires Python 3.9 or newer.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src.main
```

The local `.env` file is intentionally excluded from Git. Add an OpenRouter API
key there only when AI integration begins. Never commit or display that key.

The MVP uses OpenRouter's free multimodal model:

```text
nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
```

Process one assessment using prompt fields and an optional image:

```sh
python -m src.main \
  --module UCS1001 \
  --module-credits 6 \
  --assessment-type "Reader Response Essay" \
  --deadline 2026-10-15 \
  --weightage 30 \
  --prompt "Confirm the assessment details from the attached source." \
  --image test_case/UCS1001.png
```

The free model does not enforce JSON output at the API level. The AI Manager
therefore requests JSON, parses it, and validates every structured field before
the Logic Manager can use it. Do not upload confidential material or images
containing personal data to the free endpoint.

## Extract a complete module evidence pack

The web flow is intentionally different from manual assessment entry. The user
supplies only the module code, module credits, optional context, and one or more
screenshots for that module. One multimodal request asks Nemotron to extract
every distinct graded event it can find. A single upload can therefore create a
quiz, assignment, project milestone, presentation, and final submission at the
same time.

```text
module + credits + screenshots + optional context
                         |
                         v
        validated list of assessment events
                         |
                         v
       global credit-aware multi-module schedule
```

The assessment type, deadline, and weightage are AI-extracted fields. They do
not appear in the primary upload form. The review area exposes them only after
extraction so uncertain or missing values can be corrected. A correction is a
deterministic appended revision and does not consume another AI request.

Each event still uses the frozen assessment record contract. Module credits
remain separate in `data/modules.json`, and the entire list from one evidence
pack is appended atomically so a storage error cannot save only half an import.

## Process multiple deadlines

Use a JSON batch when several assessments must form one schedule:

```sh
python -m src.main --batch-file examples/assessments.json
```

Each list item is processed through the AI Manager independently. One malformed
item does not prevent valid items from being saved. The resulting schedule uses
only the latest `READY` revision for each record ID and keeps incomplete,
conflicting, constrained, or review-required records in persistence with a
warning.

The example intentionally contains three exact deadlines and one image whose
deadline is only a teaching week, demonstrating a usable three-block partial
schedule while preserving the incomplete record.

Module credits are stored separately in `data/modules.json`, so the frozen
assessment record contract remains unchanged. Schedule priority uses a
credit-weighted effective weightage normalized against a six-credit module:

```text
credit load = assessment weightage × module credits / 100
effective weightage = assessment weightage × module credits / 6
```

Schedule blocks are derived rather than added to the frozen record contract.
The current deliberately simple preparation rule is five days for `HIGH`, three
days for `MEDIUM`, and two days for `LOW`. Overlapping blocks remain separate so
a frontend can display them as competing workload.

To revisit a saved record, supply its record ID and the corrected field. The
previous revision remains in JSON and the corrected result is appended:

```sh
python -m src.main \
  --record-id YOUR_RECORD_ID \
  --deadline 2026-10-15 \
  --prompt "The exact deadline is now available."
```

`AI_MAX_RETRIES` is treated as the maximum total number of attempts and is
bounded to protect the free API quota. If all attempts fail, trusted input is
saved as a recoverable problem record instead of being discarded.

## Run tests

```sh
python -m pytest
```

The suite checks the frozen contract, multimodal request shape, bounded AI
retries, missing information, source conflicts, partial schedules, revision
history, corruption-safe persistence, CLI startup, absence of project-defined
classes, and confinement of terminal output to the I/O Manager.

## Run with Docker

The container runs the same procedural CLI and mounts `data/` so schedules and
revision history survive container replacement. Populate the ignored `.env`
before starting it.

Build and show the current saved schedule:

```sh
docker compose up --build
```

The website runs in the `web` container at http://127.0.0.1:5050/. Its form
extracts multiple assessments from one module evidence pack. Import additional
modules through the same form; all ready assessments are combined in the
horizontal weekly schedule.

Process the multi-assessment example through the container:

```sh
docker compose run --rm app --batch-file examples/assessments.json
```

Process one assessment by passing the same CLI flags used outside Docker:

```sh
docker compose run --rm app \
  --module INF1103 \
  --assessment-type "Procedural Project" \
  --deadline 2026-10-12 \
  --weightage 30 \
  --prompt "Process this assessment."
```

The `web` service exposes the thin frontend on http://127.0.0.1:5050/. The `app`
service remains the same independent CLI entry point.

## Run the drag-and-drop frontend

Outside Docker:

```sh
python frontend-demo/app.py
```

Open http://127.0.0.1:5000/. Uploaded images are temporary and deleted after
each AI request. The page sends module details, credits, the context prompt, and
image paths into `src.main.process_assessment()` and renders its returned
schedule. It does not duplicate business rules.

Schedule columns run horizontally by calendar week. Blocks sharing a week are
stacked vertically from LOW at the top to HIGH at the bottom and use teal,
amber, and coral priority colours.
