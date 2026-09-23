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
  --assessment-type "Reader Response Essay" \
  --deadline 2026-10-15 \
  --weightage 30 \
  --prompt "Confirm the assessment details from the attached source." \
  --image test_case/UCS1001.png
```

The free model does not enforce JSON output at the API level. The AI Manager
therefore requests one JSON object, parses it, and validates every structured
field before the Logic Manager can use it. Do not upload confidential material
or images containing personal data to the free endpoint.

## Run tests

```sh
python -m pytest
```

The initial suite checks the frozen contract, safe JSON loading, record
filtering, CLI startup, absence of project-defined classes, and confinement of
terminal output to the I/O Manager.
