# FrameSutra API reference

FastAPI source: `api.py`. The live server exposes Swagger UI at `/docs`, ReDoc at `/redoc`, and the OpenAPI schema at `/openapi.json`.

Default local API origin: `http://127.0.0.1:8000`. The Vite development server proxies `/api` to this origin. Routes are intended for the local UI; there is no API key, login, or account authentication layer.

## Conventions

- JSON responses use normal HTTP status codes. FastAPI validation errors and application errors generally return a JSON `detail` field.
- Job ownership and request limits use a client identity derived from request IP. This is not security-grade access control.
- Create routes accept multipart form data. JSON body examples below use `Content-Type: application/json`.
- The default upload limit is 512 MB per file, media duration is six hours, and a batch accepts up to three total sources.

## Health, metrics, and library

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/health` | Liveness response |
| `GET` | `/api/metrics` | Queue/job counts, capacity, disk use, retention values, process counters |
| `GET` | `/api/library?q=&limit=100` | List the current local owner’s jobs; optional title/source query and bounded limit |

## Jobs and media

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/jobs` | Create one YouTube or uploaded-media job |
| `POST` | `/api/jobs/batch` | Create one to three jobs in a batch |
| `GET` | `/api/jobs/{job_id}` | Fetch job state, stages, result, and error |
| `GET` | `/api/jobs/{job_id}/audio/{chunk_index}` | Stream a retained generated audio chunk |
| `POST` | `/api/jobs/{job_id}/retry` | Create a new job using reusable checkpoints |
| `POST` | `/api/jobs/{job_id}/retimestamp` | Create a refreshed English timestamp analysis from retained audio |
| `POST` | `/api/jobs/{job_id}/cancel` | Request cooperative cancellation |
| `DELETE` | `/api/jobs/{job_id}` | Delete job and associated files/index where possible |
| `PATCH` | `/api/jobs/{job_id}/saved` | Save or unsave a library item |

### Create one job

`POST /api/jobs` uses `multipart/form-data`:

| Field | Required | Values |
|---|---|---|
| `language` | No | `english` (default) or `hinglish` |
| `source_url` | For YouTube | Supported public YouTube URL; empty for an upload |
| `include_visuals` | No | `true` or `false` |
| `media` | For upload | One supported audio/video file |

Example with PowerShell:

```powershell
$form = @{ language = 'english'; source_url = 'https://youtu.be/VIDEO_ID'; include_visuals = 'false' }
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/api/jobs' -Form $form
```

Example with `curl` for a local upload:

```bash
curl -X POST http://127.0.0.1:8000/api/jobs \
  -F 'language=english' \
  -F 'include_visuals=false' \
  -F 'media=@lecture.mp4'
```

Successful create response: `{"job_id":"..."}`. A batch returns `{"job_ids":["...", "..."]}` and takes a JSON-encoded `sources` form field plus optional repeated `media` fields.

### Job state values

Overall states include `queued`, `running`, `complete`, `error`, `interrupted`, and `cancelled`. Pipeline stages include `audio`, `transcript`, `title`, `summary`, `extract`, `visual`, and `rag`; stage state is `pending`, `active`, `done`, `skipped`, or `error`.

## Chat and study

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/jobs/{job_id}/chat` | Retrieve persisted conversation history |
| `POST` | `/api/jobs/{job_id}/chat` | Ask a transcript/visual-evidence question |
| `GET` | `/api/jobs/{job_id}/study/{kind}` | Read saved `flashcards` or `terms`; `quiz` is intentionally ephemeral |
| `POST` | `/api/jobs/{job_id}/study/{kind}` | Generate `flashcards`, `terms`, or a fresh `quiz` |

Chat JSON body: `{"question":"What decision did the speakers make?"}`. Chat responses contain an `answer` and `sources` array with timestamp/excerpt data when available.

Study generation makes provider requests. Flashcards and terms are saved with the job; quiz responses have `persisted: false` and are not stored in SQLite. Quiz generation expects ten questions in its model output.

## Bookmarks, chapters, exports

| Method | Route | Purpose |
|---|---|---|
| `GET` | `/api/jobs/{job_id}/bookmarks` | List saved timestamps and notes |
| `POST` | `/api/jobs/{job_id}/bookmarks` | Add a bookmark |
| `DELETE` | `/api/jobs/{job_id}/bookmarks/{bookmark_id}` | Remove a bookmark |
| `PATCH` | `/api/jobs/{job_id}/chapters/{chapter_index}` | Save an edited chapter title |
| `GET` | `/api/jobs/{job_id}/export/pdf` | Generate PDF notes |

## Maintenance

| Method | Route | Purpose |
|---|---|---|
| `DELETE` | `/api/cache` | Clear reusable cache files; requires JSON `{"confirm":true}` |
| `POST` | `/api/maintenance/cleanup` | Apply automatic retention cleanup now |

Cache clearing rejects while jobs are active. It does not delete completed saved results. Job deletion and media retention are separate.

## Common error statuses

| Status | Common cause |
|---:|---|
| `400` | Invalid source/setting or missing cache-deletion confirmation |
| `404` | Unknown job or unsupported study type |
| `409` | Job cannot currently be retried/deleted, active work blocks maintenance, or transcript is unavailable |
| `413` | Request exceeds configured upload size |
| `429` | Queue is full, submission/chat limit reached, or provider rate limit |
| `502` / `503` | Provider generation failed or required API key is not configured |

## Security note

Do not expose Uvicorn’s development server publicly. The current owner identity is IP-derived; it is not a login. A public deployment needs authenticated access, HTTPS, per-user authorization, abuse protection, secure upload storage, and a production worker/queue design.
