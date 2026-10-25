<div align="center">

<img src="assets/framesutra-banner.svg" alt="FrameSutra — Every Frame Has a Story. Every Word Has an Answer." width="100%" />

# 🧩 FrameSutra · Product and Feature Analysis

### Features · APIs · Usability · Intended users · Differentiation · Business model

</div>

> **Evidence boundary:** This document describes the current repository implementation and clearly labels proposals. It does not report market research, customer interviews, competitor benchmarks, revenue, pricing, or measured user satisfaction; none of those evidence sets are present in the project.

<details>
<summary><strong>🧭 Contents</strong></summary>

- [1. Product at a glance](#1-product-at-a-glance)
- [2. Problem and solution](#2-problem-and-solution)
- [3. Intended users and jobs to be done](#3-intended-users-and-jobs-to-be-done)
- [4. Feature catalogue](#4-feature-catalogue)
- [5. API capabilities](#5-api-capabilities)
- [6. Usability analysis](#6-usability-analysis)
- [7. Uniqueness and positioning](#7-uniqueness-and-positioning)
- [8. Comparative analysis](#8-comparative-analysis)
- [9. Business model](#9-business-model)
- [10. SWOT and risks](#10-swot-and-risks)
- [11. Product validation plan](#11-product-validation-plan)
- [Related documentation](#related-documentation)

</details>

## 1. Product at a glance

| Product element | Current definition |
|---|---|
| Name | **FrameSutra** |
| Promise | *Every Frame Has a Story. Every Word Has an Answer.* |
| Category | Local-first video understanding, transcription and transcript-grounded Q&A |
| Core workflow | Submit → transcribe → analyze → index evidence → review → export/save |
| Interface | React/Vite browser app; an older Streamlit interface remains |
| Backend | FastAPI with a bounded in-process Python worker pool |
| Local stores | SQLite for jobs and related records; Chroma for local embeddings/evidence |
| Provider connections | Groq for text and optional vision; Sarvam for the current Hinglish path |
| License | MIT for project code; separate third-party licenses and provider terms apply |
| Operating model | One local operator; no login or multi-user isolation |

## 2. Problem and solution

### Problem description

Long recordings are hard to navigate. Reviewing them linearly costs time, while a text transcript alone can be difficult to turn into decisions, action lists or study material. General summaries can omit context, and a reviewer may not know where a generated claim came from. Uploading a complete recording to a hosted service can also be unsuitable for private material.

### Proposed solution

FrameSutra combines a local media/transcription path, structured analysis, transcript retrieval, optional visual notes and a library of review artifacts. A user asks a question and receives an answer grounded by retrieved evidence snippets; timestamps help locate the corresponding part of the source. The app exposes local job/storage controls and tells the user when optional features call outside providers.

### Value proposition

> **One local workspace to turn a recording into searchable notes and evidence-linked study material, with provider use disclosed per feature.**

"Local workspace" describes where the application and several processing steps run. It does not mean every operation is offline: Hinglish audio can go to Sarvam, and transcript text/chunks, prompts, retrieved chat sources, study excerpts or optional sampled frames can go to Groq.

## 3. Intended users and jobs to be done

These are **intended user groups inferred from the feature set**, not confirmed customer segments.

| User archetype | Typical job | Helpful FrameSutra functions | Cautions |
|---|---|---|---|
| 🎓 Student / self-learner | Revisit lectures, find a definition, prepare a review set | Transcript search, summary, chapters, flashcards, key terms, quiz | Check notes and answers against the source; provider costs/limits may apply |
| 🧑‍🏫 Educator / trainer | Turn an authorized lesson recording into notes and study material | Structured output, transcript, chapters, exports | Obtain recording permissions and review generated material before sharing |
| 🔬 Researcher | Search interviews, talks or demonstrations for themes and passages | Searchable transcript, source excerpts, bookmarks, local library | Sensitive interview audio may still be sent to configured providers for selected features |
| 🎬 Creator / editor | Find topics and key moments in long-form media | Transcript segments, approximate timestamps, visual observations | Timestamps are not guaranteed word-level edits; visual analysis is optional and provider-backed |
| 💼 Meeting reviewer | Locate decisions, action items and unresolved questions | Decisions, actions, open questions, chat, bookmarks and exports | Do not process confidential meetings without organizational approval |
| 🏠 Local privacy-conscious user | Keep the core workspace and index on a personally controlled machine | Local Whisper path, local embeddings, local SQLite/Chroma storage | Must understand external provider transfers and protect local files |

### Poor-fit users in the current version

- Organizations needing authenticated multi-user accounts, access roles, audit trails or tenant separation.
- Users requiring guaranteed word-level timestamps, certified transcripts or professional-grade diarization.
- Users who require fully offline operation while also expecting provider-backed Hinglish, Groq analysis or Groq vision.
- Public services expecting high availability, distributed queues, abuse prevention or an operations SLA.

## 4. Feature catalogue

### 4.1 Source intake and processing

| Feature | Current behavior | User outcome |
|---|---|---|
| YouTube URL | Validates supported public YouTube hosts and requests audio-focused acquisition | Process an eligible public video without a manual download step |
| Local upload | Accepts supported audio/video types subject to FFmpeg and backend limits | Analyze a local recording |
| Batch intake | Accepts up to three source items in one batch | Queue several related sources in one session |
| Language choice | English or Hinglish processing path | Select the path that matches the recording |
| Optional visual analysis | Sample/deduplicate frames from local video and request descriptions | Add visual context to transcript review |
| Guardrails | Upload size, media duration, job capacity and request rate controls | Reject out-of-policy work before or during admission |

### 4.2 Understanding and evidence

| Feature | Current behavior | Boundary |
|---|---|---|
| Speech-to-text | Whisper locally for English; Sarvam API for Hinglish | Accuracy depends on audio, language mix, model and provider |
| Structured notes | Title, summary, action items, decisions and open questions | Generated text may be incomplete or wrong |
| Chapters | Topic groupings derived from transcript chunks | Approximate grouping, not a professionally edited chapter list |
| Transcript search | Search within transcript segments; timestamps can be selected | Some timestamps are approximate chunk starts |
| RAG chat | Retrieve transcript/visual evidence, then ask configured Groq model | An answer can still misinterpret evidence; citations are not proof |
| Study tools | Flashcards, key terms and ten-question quiz | Quiz remains ephemeral in the UI; flashcards and terms are persisted |
| Visual notes | Optional sampled-frame descriptions for supported local video | Selected frames are sent to the configured vision provider |

### 4.3 Library and operations

| Feature | Current behavior |
|---|---|
| Job progress | Shows queue/job and stage states; active jobs are polled by the interface |
| Checkpoint retry | Creates a new job that reuses eligible retained stage artifacts |
| Cooperative cancellation | Sets a cancellation request checked at stage/chunk boundaries; cannot forcibly interrupt every active call |
| Analysis library | Search, reopen, save/unsave, retry eligible items and delete jobs |
| Bookmarks and chapter edits | Persist timestamp notes and edited chapter titles |
| Exports | PDF notes, Markdown/JSON report and transcript; retained audio chunks may be played/downloaded |
| System page | Shows queue, job, disk and process counters; manual retention cleanup and selected cache clearing |
| Theme and responsive UI | Site-wide light/dark switch, mobile navigation and reduced-motion-aware styling |
| User agreement | Privacy/user-agreement dialog and acceptance control before job submission |

### 4.4 Defaults that affect product use

Defaults in the project configuration include one worker, three outstanding jobs, up to three batch sources, 512 MB per upload, six-hour media, five job submissions per hour (also one per twenty seconds), fifteen chat/study requests per minute, 30-day expiry for unsaved jobs and seven-day media cleanup. They are configurable and can change. These controls are rate/capacity limits, not identity security.

## 5. API capabilities

The complete request examples, form fields, states and error codes live in the [API reference](API_REFERENCE.md). Current route groups:

| Capability | Routes |
|---|---|
| Service | `GET /api/health`, `GET /api/metrics` |
| Library | `GET /api/library` |
| Submit jobs | `POST /api/jobs`, `POST /api/jobs/batch` |
| Read and play results | `GET /api/jobs/{job_id}`, `GET /api/jobs/{job_id}/audio/{chunk_index}` |
| Job lifecycle | `POST /api/jobs/{job_id}/retry`, `/retimestamp`, `/cancel`; `DELETE /api/jobs/{job_id}`; `PATCH /api/jobs/{job_id}/saved` |
| Bookmarks | `GET/POST /api/jobs/{job_id}/bookmarks`; `DELETE /api/jobs/{job_id}/bookmarks/{bookmark_id}` |
| Chapters | `PATCH /api/jobs/{job_id}/chapters/{chapter_index}` |
| Chat | `GET/POST /api/jobs/{job_id}/chat` |
| Study | `GET/POST /api/jobs/{job_id}/study/{kind}` |
| Export | `GET /api/jobs/{job_id}/export/pdf` |
| Maintenance | `DELETE /api/cache` with confirmation; `POST /api/maintenance/cleanup` |

**API security boundary:** local routes do not require login. The current owner key is derived from the request IP, so another process/user able to reach the service may share that identity. Keep the development API on loopback and do not treat it as safe for a public network.

## 6. Usability analysis

### Strengths observed in the implementation/design

- Source types are grouped into YouTube, upload and batch workflows.
- The submission screen surfaces language, optional visual analysis and agreement requirements.
- Progress is represented as pipeline stages with error/retry/cancel concepts.
- Result views separate overview, transcript, visuals, chapters, study and chat.
- The library and system screen expose management/maintenance rather than leaving all data hidden in files.
- Theme preference persists in browser storage; layouts respond to narrow viewports.
- Design documentation describes accessible names, Escape handling and reduced-motion support.

### Usability gaps requiring research

- No documented usability sessions, satisfaction score, completion time or task-success rate.
- The initial setup still requires Python, Node, FFmpeg, model downloads and provider credentials.
- Long model/provider stages can take time; first-run latency varies by device and network.
- Approximate timestamps and AI uncertainty need careful interpretation by users.
- Theme consistency does not equal a completed contrast or screen-reader audit.
- Single-user assumptions and local data locations may be unfamiliar to non-technical users.

### Suggested usability study

Recruit consented representatives from at least two intended user groups. Ask each to submit a non-sensitive sample, locate a specific passage, create a bookmark, export notes, explain which content leaves the machine and delete the analysis. Record task completion, time, errors, confidence and privacy comprehension. Report sample size and method; do not generalize beyond the participants.

## 7. Uniqueness and positioning

### Differentiating combination

1. **Local-first core workflow:** media conversion, English Whisper, embeddings and retrieval can stay on the host.
2. **Evidence-oriented answers:** RAG connects answers to retrieved text excerpts and approximate time references.
3. **Review, not just summary:** results continue into bookmarks, chapter edits, study sets, library retention and exports.
4. **Hybrid language/visual routes:** configurable Hinglish support and optional sampled visual notes extend transcript-only use.
5. **Operational transparency:** progress stages, checkpoints, cleanup and provider disclosure are part of the app and docs.

The product’s uniqueness is **compositional**. The repo does not claim a proprietary speech model, novel embedding algorithm, or independently measured accuracy advantage.

### Positioning statement

For a person who needs to revisit long recordings, FrameSutra is a locally run video-review workspace that combines searchable transcripts, structured notes and evidence-linked Q&A. Compared with manual replay it automates organization; compared with a transcript-only tool it adds review/study features; compared with a cloud-first workflow it keeps several core steps on the user’s host while still disclosing provider-backed features.

## 8. Comparative analysis

The comparison below contrasts **workflow categories**, not named commercial products. No competitor teardown or feature verification was performed.

| Dimension | Manual replay | Cloud-first summarization category | Transcript search category | FrameSutra |
|---|---|---|---|---|
| Input handling | User plays media | Usually service upload/link, varies | Transcript/file, varies | Local file or supported YouTube URL; small batches |
| Summarization | Manual notes | Often available; vendor-specific | May be absent | Structured analysis through configured Groq model |
| Find a spoken point | Replay/seek | Tool-specific search | Text search | Transcript search plus retrieval chat |
| Evidence context | Direct source only | Varies by product | Search result text | Retrieved excerpts and approximate timestamps |
| Study material | Manual creation | Product-specific | Usually not the core focus | Flashcards, terms and ephemeral quiz |
| Visual understanding | Manual video review | Vendor-specific | Usually transcript-centered | Optional local frame sampling with external vision call |
| Data locality | User-controlled if no sharing | Depends on provider | Depends on implementation | Hybrid; local core plus selected external calls |
| Multi-user admin | Not applicable | Varies | Varies | Not available |
| Setup effort | Low | Often low | Varies | Higher: Python/Node/FFmpeg/models/API keys |

**Interpretation:** FrameSutra trades setup simplicity for local control and workflow breadth. It should not be advertised as more accurate, cheaper or more private than named alternatives without a controlled comparative evaluation and verified provider policies.

## 9. Business model

### Current state

The current project is a source repository with MIT-licensed project code. It has no hosted product, user accounts, payment system, published pricing, SLA or recorded revenue. Users may need to supply third-party API keys and cover any applicable provider usage or hardware costs.

### Business Model Canvas — proposed, not implemented

| Canvas block | Candidate hypothesis |
|---|---|
| Customer segments | Students/self-learners, educators, researchers and individual knowledge workers with authorized long-form recordings |
| Value propositions | Searchable notes and evidence-linked Q&A from a local review workspace; flexible provider choice; study and export functions |
| Channels | GitHub repository, project documentation, educational demos and community referrals |
| Customer relationships | Self-service setup and documentation first; support would require an explicit maintainer/support plan |
| Revenue streams | Optional donations/support; paid setup/support; a future team edition only after access control and hosting safeguards exist |
| Key resources | Codebase, documentation, maintainers, supported models/providers, local-user feedback and release process |
| Key activities | Maintain dependencies, adapt provider integrations, improve citations/usability, secure deployment and respond to issues |
| Key partners | Model/API providers and open-source dependency maintainers; no formal partnership is claimed |
| Cost structure | Development/maintenance time, user hardware/storage, model downloads, provider usage, hosting/support if introduced |

### Candidate packaging

- **Community local edition (current direction):** user runs the app, owns local files and supplies credentials where needed.
- **Assisted setup/support (possible):** paid installation or maintenance service; validate support demand before launch.
- **Team/hosted edition (future only):** requires authentication, per-user authorization, encryption/retention controls, secure uploads, queue isolation, monitoring, provider contracts and legal review before it is commercially viable.

No price, margin or market-size estimate is included because no primary market or cost research has been conducted.

## 10. SWOT and risks

| Strengths | Weaknesses |
|---|---|
| Broad review workflow; local embeddings; structured results; visible job controls; multiple output formats | Higher setup burden; no login; one-process queue; model/device variability; no committed test suite or measured outcomes |

| Opportunities | Threats |
|---|---|
| Improve citations, accessibility, Indic-language support, offline options and user validation; add secure team deployment later | Provider/API changes, usage cost, YouTube changes, model quality, local data loss, unauthorized media use, public exposure of unauthenticated API |

Risk controls already documented include provider disclosure, loopback startup, input/rate limits, local retention controls, source verification reminders and warnings against public exposure. They reduce some operational risk but do not substitute for security testing or authentication.

## 11. Product validation plan

| Question | Method | Evidence to record |
|---|---|---|
| Can target users finish a first analysis? | Moderated task study with a short authorized sample | Completion rate, time, errors, setup blockers |
| Are answers supported by the cited source? | Human review of a fixed question set against transcript/source | Support rating, citation correctness, unsupported-claim count |
| Is transcription usable for target recordings? | Ground-truth sample and WER/CER by language/noise condition | Dataset description, score, model/configuration and limitations |
| Does the local workflow provide practical control? | Ask participants to identify provider transfers and delete their data | Comprehension and successful deletion evidence |
| Is the runtime cost acceptable? | Record stage timing, CPU/RAM/disk and provider usage for fixed sample sizes | Device specs, durations, model IDs, provider account pricing/date |
| Can the app operate reliably? | Repeat API/restart/cleanup/retry scenarios | Logs, state transitions, retained files and recovery outcome |

### Product claims to keep evidence-based

- Say **“local-first”**, not “fully offline.”
- Say **“evidence-linked answer”**, not “guaranteed correct answer.”
- Say **“approximate timestamp”** where segment timing is not word-aligned.
- Say **“optional provider-backed visual analysis”**, not “private local vision.”
- Describe multi-user, hosted and business offerings as future proposals until implemented and reviewed.

## Related documentation

- [Comprehensive project report](PROJECT_REPORT.md)
- [User manual](USER_MANUAL.md)
- [API reference](API_REFERENCE.md)
- [Architecture and data stores](ARCHITECTURE.md)
- [Product design and interaction states](PRODUCT_DESIGN.md)
- [Operations, settings and reset](OPERATIONS.md)
- [Privacy, terms and user agreement](PRIVACY_AND_TERMS.md)
