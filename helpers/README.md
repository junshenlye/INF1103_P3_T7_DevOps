# Helpers

This folder contains development adapters, not assessment business rules.

- `api_server.py` exposes the procedural `src/` flow on port 8000 for the
  separately run frontend.
- `progress_tracker.py` keeps short-lived extraction diagnostics in memory.

Assessment extraction, validation, priority, scheduling, and persistence
selection remain in `src/`.
