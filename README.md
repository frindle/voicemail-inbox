# voicemail-inbox

A small, self-hosted voicemail inbox with automatic transcription and DNC / robocall-complaint tooling. Built for a private LAN.

## What it does
- **Ingest** — an iPhone Shortcut (or any client) POSTs a voicemail recording to `/ingest`.
- **Transcribe** — a companion worker (`worker.py`) polls for new voicemails, transcribes them with [faster-whisper](https://github.com/SYSTRAN/faster-whisper), and posts the text back.
- **Screen** — each transcript is run through deterministic robocall / spam / DNC-violation heuristics, and the app pre-fills FTC/FCC complaint forms (fill-only, never auto-submitted).

## Architecture
- `server.py` — FastAPI/uvicorn single-file app (inbox, ingest, screening, complaint autofill).
- `worker.py` — decoupled faster-whisper polling transcription worker.
- Two containers via `docker-compose.yml`; the worker shares the app's network namespace.

## Run
```bash
docker compose up -d --build
```
Then point your client at `http://<host>:8000/ingest`.

### Configuration
| Env | Default | Notes |
|-----|---------|-------|
| `DATA_DIR` | `/data` | SQLite DB + audio blobs (persist this volume). |
| `AUTH_TOKEN` | *(unset)* | Optional. When set, requires `Authorization: Bearer <token>`; unset = open (intended for a trusted LAN). |
| `WHISPER_MODEL` | `small.en` | faster-whisper model; bump to `medium.en` for noisier audio. |
| `POLL_INTERVAL` | `15` | Worker poll cadence (seconds). |

## Notes
This is a personal-LAN tool. Auth is optional by design; do not expose it to the public internet without setting `AUTH_TOKEN` (and ideally a reverse proxy with TLS).
