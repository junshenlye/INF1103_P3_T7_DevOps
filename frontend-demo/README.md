# Stackplan frontend demo

This is a thin Flask adapter over the procedural core in `src/`. It contains no
assessment, priority, scheduling, AI, or persistence rules.

It supports:

- drag-and-drop image evidence;
- normal-language context prompts;
- persistent module-credit profiles;
- credit-weighted schedule priority;
- horizontal week columns;
- vertical same-week stacking with HIGH priority at the bottom;
- priority colour coding.

Requires Python 3.9 or newer. Run these commands from the repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python frontend-demo/app.py
```

Open http://127.0.0.1:5000/ in your browser.

Uploaded images are request-scoped temporary files and are deleted after the
procedural pipeline returns. Do not upload confidential or personal material to
the free AI endpoint.
