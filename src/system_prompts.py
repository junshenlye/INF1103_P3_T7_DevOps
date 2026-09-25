"""Central prompt text and prompt builders for assessment extraction."""

import json


PACING_SYSTEM_PROMPT = """Extract academic assessment facts into the supplied JSON schema.

Rules:
- Never invent dates, weeks, weights, recurrence, credits, or assessment status.
- Do not give study advice or calculate priority, pressure, or relative scores.
- Return partial facts when evidence is incomplete; use null for unknown fields.
- Keep feedback compact: one missing-information item per assessment and no more
  than three checklist items for the module. Do not repeat the same issue.
- Participation, attendance, tutorial engagement, and student engagement are
  participation assessments, not assignments.
- A percentage covering repeated participation is the total trimester weight.
  Use per_occurrence only when the source explicitly says each occurrence has
  that weight.
- Return JSON only. Use a hard error only when the request cannot be processed.
"""

LEGACY_SYSTEM_PROMPT = """Extract academic assessment facts without guessing.
Return every reliable fact and turn uncertainty into concise evidence requests.
"""


def build_pacing_prompt(module, trimester_context, document_text):
    """Build the user prompt for one module and its evidence."""
    calendar = [
        {
            "week": item["week"],
            "start_date": item["start_date"],
            "end_date": item["end_date"],
            "label": item["label"],
        }
        for item in trimester_context.get("weeks", [])
    ]
    return (
        "Extract every graded assessment from this module. Recognise quizzes, "
        "assignments, projects, reports, presentations, labs, practicals, "
        "midterms, final exams, and participation. Exclude make-up/replacement "
        "tests, optional activities, practice, and formative work unless clearly "
        "graded for this student. Keep items sharing one weight together. Split "
        "only independently weighted items. For recurring work, give exact weeks "
        "when known. For multi-week work, give start and end weeks. A weight of "
        "30 means 30%. Preserve supplied credits and use ISO YYYY-MM-DD dates.\n\n"
        f"Module: {module['module_name']}\n"
        f"Credit units: {module.get('credit_units')}\n"
        f"Additional context: {module.get('additional_context') or 'None'}\n"
        f"Trimester calendar: {json.dumps(calendar, separators=(',', ':'))}\n"
        f"Document text:\n{document_text or 'None; inspect supplied images.'}"
    )


def build_legacy_prompt(input_data):
    """Build the compatibility prompt used by the former one-module workflow."""
    module = input_data["module"].strip().upper()
    context = input_data.get("prompt", "").strip()
    return (
        f"Extract every graded component for module {module} from all evidence. "
        "Copy source names, including unfamiliar assessment formats. Keep repeated "
        "activities together when they share one collective weight; split only "
        "independently weighted components. Scan all evidence before responding. "
        "Use deadline Week N only for one exact stated week; otherwise use null. "
        "Never guess or divide a shared weight. A weight of 15% must be returned "
        "as 15, not 0.15. Return all reliable components even when some facts are "
        "unclear. Keep comments and actionable evidence requests short, and do not "
        "repeat confirmed facts. "
        f"Additional context: {context or 'None'}"
    )
