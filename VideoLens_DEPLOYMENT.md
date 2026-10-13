# VideoLens — Deployment Quick Guide

This guide accompanies `README.md`. For the complete product, architecture, processing flow and troubleshooting documentation, see the main README.

## Recommendation

- **Public demo:** Hugging Face Spaces with the Docker SDK, using a short non-sensitive test video first.
- **Repeated 12-hour videos:** a VPS or cloud VM with Docker, persistent disk, sufficient CPU/RAM and a queue/worker design before multi-user production.
- **Streamlit Community Cloud:** only a constrained demo is recommended because the application uses PyTorch/Whisper, Sentence Transformers, Chroma and FFmpeg.

## Hugging Face Docker Space checklist

1. Keep the full Python package structure intact: `app.py`, `core/`, `utils/`, `Requirements.txt` and required helpers.
2. Copy `deploy/huggingface/Dockerfile`, `entrypoint.sh` and `.dockerignore` to the repository root when deploying.
3. Create a Hugging Face Space using the Docker SDK. Use `deploy/huggingface/README_SPACE.md` as the Space's `README.md` so that Docker metadata is present at the top.
4. Add `GROQ_API_KEY` as a secret. Add `SARVAM_API_KEY` only if Hinglish mode will be used. Add model IDs as variables and verify availability with providers.
5. Build/deploy and inspect both build logs and application logs.
6. Test in this order: local short audio → English transcription → Groq summary/chat → Hinglish → local visual analysis → long media.
7. Attach a Storage Bucket at `/data` only if you want the supplied entrypoint to persist model caches, checkpoints, media and Chroma data. This can retain sensitive transcripts and uploads; use a retention/cleanup policy. Without a bucket, data remains ephemeral.

## Model behavior on a cloud host

- Whisper model weights are downloaded the first time a selected checkpoint is loaded, unless cached.
- Sentence Transformer weights are downloaded from Hugging Face Hub on first use, unless cached.
- Groq text/vision models run remotely via API; they are not downloaded into the container.
- Sarvam speech processing runs remotely; audio pieces are sent to Sarvam in Hinglish mode.
- A fresh/ephemeral container may download model weights again. A persistent disk or storage bucket can help retain caches.

## Before making it public

- Never commit `.env` or secrets.
- Restrict who can upload and analyze files if recordings can be sensitive.
- Add upload duration/size caps, output cleanup and rate limits.
- The current app runs processing synchronously in the Streamlit process. For reliable multi-user or very long jobs, use background workers, a job queue, durable job state and cancellation.
- Keep local media and generated indexes out of Git; they may contain personal or confidential data.
