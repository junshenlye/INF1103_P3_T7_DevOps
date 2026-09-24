"""Small in-memory progress tracker for local extraction jobs."""

import threading
import time
from uuid import uuid4


JOBS = {}
JOBS_LOCK = threading.Lock()
JOB_TTL_SECONDS = 15 * 60


def cleanup_finished_jobs():
    """Forget completed jobs after the short local debugging window."""
    cutoff = time.time() - JOB_TTL_SECONDS
    with JOBS_LOCK:
        expired = [
            job_id
            for job_id, job in JOBS.items()
            if job["status"] in ("complete", "failed")
            and job["updated_at"] < cutoff
        ]
        for job_id in expired:
            del JOBS[job_id]


def active_job_count() -> int:
    """Return the number of queued or running jobs."""
    with JOBS_LOCK:
        return sum(
            job["status"] in ("queued", "running") for job in JOBS.values()
        )


def create_job() -> str:
    """Create one progress record and return its opaque identifier."""
    job_id = str(uuid4())
    now = time.time()
    with JOBS_LOCK:
        JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "stage": "queued",
            "message": "Evidence pack queued for processing.",
            "attempt": 0,
            "max_attempts": None,
            "event_count": None,
            "created_at": now,
            "updated_at": now,
            "events": [
                {
                    "stage": "queued",
                    "message": "Evidence pack queued for processing.",
                    "elapsed_seconds": 0.0,
                }
            ],
            "result": None,
        }
    return job_id


def update_job(job_id: str, progress_event=None, **changes):
    """Update one job and append a concise visible diagnostic event."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return
        now = time.time()
        if progress_event:
            stage = progress_event.get("stage", job["stage"])
            message = progress_event.get("message", job["message"])
            job["stage"] = stage
            job["message"] = message
            for key in ("attempt", "max_attempts", "event_count"):
                if progress_event.get(key) is not None:
                    job[key] = progress_event[key]
            visible_event = {
                "stage": stage,
                "message": message,
                "elapsed_seconds": round(now - job["created_at"], 1),
            }
            if progress_event.get("attempt") is not None:
                visible_event["attempt"] = progress_event["attempt"]
            if progress_event.get("max_attempts") is not None:
                visible_event["max_attempts"] = progress_event["max_attempts"]
            previous = job["events"][-1] if job["events"] else None
            if previous is None or any(
                previous.get(key) != visible_event.get(key)
                for key in ("stage", "message", "attempt")
            ):
                job["events"].append(visible_event)
        job.update(changes)
        job["updated_at"] = now


def public_job(job_id: str):
    """Return a JSON-safe view without local paths or submitted source data."""
    with JOBS_LOCK:
        job = JOBS.get(job_id)
        if job is None:
            return None
        return {
            "id": job["id"],
            "status": job["status"],
            "stage": job["stage"],
            "message": job["message"],
            "attempt": job["attempt"],
            "max_attempts": job["max_attempts"],
            "event_count": job["event_count"],
            "elapsed_seconds": round(time.time() - job["created_at"], 1),
            "events": [dict(event) for event in job["events"]],
            "result": dict(job["result"]) if job["result"] else None,
        }
