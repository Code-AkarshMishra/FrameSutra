# Privacy, terms, and user agreement

This document describes the current local FrameSutra implementation. It is project documentation, not a provider policy or jurisdiction-specific legal notice. Project credit: built with effort by Akarsh Mishra. No support contact address, legal entity, governing jurisdiction, or software license has been supplied.

## Data-flow summary

| Data | Where it is processed or stored | When it may leave the host |
|---|---|---|
| Local uploaded media | Saved under the project’s `uploads/` and processed by the backend | Hinglish transcription sends audio pieces to Sarvam. Optional frame descriptions send sampled frames to Groq Vision. |
| YouTube source | URL and derived audio are handled by the backend and `yt-dlp` | Audio pieces can be sent to Sarvam for Hinglish; generated text can be sent to Groq for analysis/chat. `yt-dlp` contacts YouTube. |
| English speech audio | Prepared and transcribed by local Whisper on the backend host | Not sent to Sarvam by the English transcription path; provider-backed analysis still uses transcript content. |
| Transcript, prompts, study excerpts | Job result/checkpoint data is stored in local SQLite; retrieval index is local Chroma | Groq may receive transcript excerpts or selected transcript content for title, summary, extraction, answers, or study generation. |
| Job metadata, chat, bookmarks, study sets | Local `videolens.sqlite3` database | Not intentionally sent as a separate analytics feed by this code. Chat prompts and retrieved excerpts are sent for generated answers. |
| Temporary media and derived files | `uploads/`, `downloads/`, and `.cache/` on the host | Provider-bound audio or selected frames are transmitted when the corresponding feature is used. |
| Browser state | Browser `localStorage` retains active job and batch IDs plus the theme preference | Job IDs are sent to the local API as normal job lookups. The theme preference stays in the browser. |

The database file’s current legacy filename is `videolens.sqlite3`; the product is now named FrameSutra. The filename is retained for local-data compatibility.

The app does not provide authentication. The API associates jobs and rate limits with request IP-derived ownership. This is a local single-user convenience boundary, not secure account isolation. Anyone with access to the host, local files, or reachable API may be able to access or change data.

## Retention and deletion

Defaults in the current configuration:

- Unsaved completed, failed, interrupted, and cancelled job records expire after 30 days.
- Saved jobs are excluded from automatic job expiry until the user deletes them.
- Media files are removed after seven days by periodic cleanup.
- Cache files have separate cleanup behavior; retained model weights may be outside this project’s directories.
- Clearing reusable caches does not delete saved analysis records.

Operators can change the job and media age settings in `.env`. Use the library’s delete action to remove an analysis, System cleanup/cache controls for reusable files, or a full project reset after stopping the API. Files copied elsewhere or retained by an external provider are outside this application’s deletion controls.

## Provider disclosure

The exact provider model IDs are configurable and provider availability can change. Current code uses:

- **Groq:** configured text model for analysis, chat, study sets, and PDF review questions. When visual analysis is enabled, selected frame images and prompts are sent to the configured Groq vision model.
- **Sarvam:** configured speech-to-text/translation endpoint for Hinglish. Audio is split into short pieces before the request.
- **YouTube / yt-dlp:** network access is used to inspect and download audio for supported public links.
- **Hugging Face model hub:** first use may download Whisper and/or sentence-transformer model weights to the host cache.

Review the applicable provider terms and data practices for your account before processing confidential recordings. The project cannot state provider retention or training practices on a provider’s behalf.

## User agreement

By submitting a URL or file, you agree that:

1. You have the rights, permission, and necessary consent to process the recording and its contents.
2. Your use complies with applicable law, copyright, privacy obligations, workplace/school requirements, and source-platform rules.
3. You understand which selected features send audio, frames, transcript excerpts, or prompts to configured external providers.
4. You are responsible for securing the host machine, API access, `.env` credentials, backups, and generated data.
5. You will review the original recording for important details because transcripts, summaries, citations, timestamps, and generated study material can be wrong or incomplete.

The UI asks users to check an agreement box before starting an analysis. That checkbox is a product acknowledgement; it does not create authentication or independently verify permissions.

## Terms of use

Use the project lawfully and only with media you are permitted to process. Do not use generated output as medical, legal, financial, safety, or other professional advice. The software is provided as a project tool without a guarantee of accuracy, availability, or suitability for a particular purpose. Third-party services remain subject to their own terms and availability.

Before presenting FrameSutra as a public service or redistributing it, provide and review a support contact, license, jurisdiction, user support process, authentication, and deployment security controls. Do not invent these details in this document.

## Practical security checklist

- Keep `.env` out of source control and restrict access to API keys.
- Keep Uvicorn on `127.0.0.1` for personal use. Do not expose the development server publicly.
- Do not upload confidential media unless you have authorization and accept the configured provider data flows.
- Protect `videolens.sqlite3`, `vector_db/`, `uploads/`, `downloads/`, and backups as potentially sensitive data.
- Delete data that is no longer needed and check backups separately.
