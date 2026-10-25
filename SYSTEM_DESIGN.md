# FrameSutra system design

This file summarizes the implemented API limits and operating assumptions. See [Architecture](docs/ARCHITECTURE.md) for the complete component and data-flow diagrams, [API reference](docs/API_REFERENCE.md) for routes, and [Operations](docs/OPERATIONS.md) for configuration and reset steps.

## Current runtime model

- React/Vite frontend communicates with the FastAPI backend under `/api`.
- FastAPI uses SQLite for jobs, checkpoints, chats, bookmarks, study sets, answer cache, and rate-limit windows.
- A single API process runs an in-process thread pool. Default worker count is one; default capacity is three active plus queued jobs.
- Chroma persists transcript and optional visual evidence embeddings locally. Active RAG chains are cached in API memory.
- On process startup, work that was still queued or running is marked interrupted. Eligible jobs can be retried using persisted checkpoints if the referenced media remains available.

## Limits and controls

Defaults are read from `.env.example` and `api.py`:

| Control | Default |
|---|---:|
| Worker threads | 1 |
| Outstanding jobs | 3 |
| Batch size | 3 sources |
| Upload size | 512 MB per file |
| Media duration | 6 hours |
| Job submissions | 5 per hour; one per 20 seconds |
| Chat and study requests | 15 per minute |
| Unsaved job retention | 30 days |
| Media retention | 7 days |

Limits are IP-derived for the current local ownership model. This is not authentication, tenant isolation, or a public abuse-control system.

## Checkpoints, retry, and cancellation

Audio paths, transcripts, analysis output, and visual evidence are checkpointed by stage. A retry creates a new job and reuses available checkpoints. If media has expired, the job may continue only when a later checkpoint is sufficient. Cancellation is cooperative at stage/chunk boundaries; an active native model call, download, or provider request may not stop immediately.

## Retention and cache behavior

- Unsaved completed, failed, interrupted, and cancelled jobs expire after the configured job retention period.
- Saved analyses are retained until manually deleted.
- Media files are removed after the configured media retention age.
- Startup and daily cleanup apply configured expiration.
- Manual cleanup is available from the System page.
- Cache clearing is separate from saved result deletion; it removes selected transcript, analysis, frame, and YouTube-audio caches and rejects while jobs are active.
- Model weight caches can be outside the repository and are not necessarily cleared by the app.

## Data stores

`videolens.sqlite3` is the legacy-compatible filename for the FrameSutra job/history store; it remains unchanged so saved local records continue to work. `vector_db/` holds Chroma collections. `uploads/`, `downloads/`, and `.cache/` contain media and generated stage data. Browser localStorage holds active/batch job IDs and the theme preference. Treat these locations as potentially sensitive and keep them out of Git.

Stop the API before making a consistent SQLite/WAL and vector-store backup. A database-only restore can leave missing media or indexes.

## Provider and cost notes

English Whisper and embeddings run on the host. Hinglish audio is sent to Sarvam. Groq receives content needed for summary, extraction, chat, study generation, PDF review questions, and optional frame descriptions. Model quotas, costs, availability, and retention are governed by the provider account and may change.

## Operational boundary

Do not run multiple Uvicorn worker processes with this design. The queue is not distributed and in-memory counters/RAG chains are process-local. Do not expose the development API publicly without authentication, per-user authorization, TLS, durable workers, monitoring, and a reviewed data policy. See [Deployment](FrameSutra_DEPLOYMENT.md).
