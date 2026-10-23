# services/ingest

Pulls data from partner APIs on a schedule. Jobs are registered in `registry.py`, and each
job has its own module under `jobs/`.

Jobs must take the run timestamp as an argument.
Never call `datetime.now()` or `datetime.utcnow()` inside a job, because re-running
yesterday's job would otherwise produce today's data.

Retries are handled by the scheduler, so jobs should not add their own retry loops.

Partner credentials are injected through environment variables by the scheduler.
