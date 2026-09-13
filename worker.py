"""Whisper transcription worker for the voicemail inbox.

Standalone polling process (NOT imported by server.py). Each cycle it lists
voicemails via GET /api/list, transcribes every row still in `processing`
with faster-whisper, and writes the result back via POST
/internal/transcript -- which is what flips the row to `done`.

The module imports cleanly WITHOUT faster-whisper installed: the model import
and construction are deferred into load_model(), called only from main().
"""
import logging
import os
import tempfile
import time

import requests

log = logging.getLogger("voicemail-worker")


def _env():
    """Read worker configuration from the environment (with defaults)."""
    return {
        "base_url": os.environ.get("VOICEMAIL_URL", "http://127.0.0.1:8000"),
        "auth_token": os.environ.get("AUTH_TOKEN", ""),
        "model_name": os.environ.get("WHISPER_MODEL", "small.en"),
        "compute_type": os.environ.get("WHISPER_COMPUTE_TYPE", "int8"),
        "device": os.environ.get("WHISPER_DEVICE", "cpu"),
        "poll_interval": float(os.environ.get("POLL_INTERVAL", "15")),
        "model_dir": os.environ.get("WHISPER_MODEL_DIR", "/models"),
    }


def load_model():
    """Construct the Whisper model. faster-whisper is imported here, not at
    module import time, so this file can be imported (and tested) without it."""
    from faster_whisper import WhisperModel

    cfg = _env()
    return WhisperModel(
        cfg["model_name"],
        device=cfg["device"],
        compute_type=cfg["compute_type"],
        download_root=cfg["model_dir"],
    )


def process_once(base_url, model, session, auth_token=""):
    """One poll cycle: transcribe every `processing` voicemail and POST the
    transcript back. One failing row never stops the others."""
    headers = {}
    if auth_token:
        headers["Authorization"] = "Bearer " + auth_token

    resp = session.get(base_url + "/api/list")
    rows = resp.json()

    for row in rows:
        if row.get("status") != "processing":
            continue  # done (or anything else) is never re-transcribed/POSTed
        tmp_path = None
        try:
            with session.get(base_url + row["audio_url"], stream=True) as ar:
                f = tempfile.NamedTemporaryFile(delete=False)
                tmp_path = f.name
                for chunk in ar.iter_content(chunk_size=8192):
                    f.write(chunk)
                f.close()

            segments, info = model.transcribe(tmp_path)
            duration = getattr(info, "duration", None)
            parts = []
            last_pct = 0
            for seg in segments:
                parts.append(seg.text.strip())
                if duration:  # info.duration can be None/0 -> skip progress
                    pct = int(min(100, max(0, (seg.end / duration) * 100)))
                    if pct > last_pct:
                        last_pct = pct
                        try:
                            session.post(
                                base_url + "/internal/progress",
                                json={"id": row["id"], "progress": pct},
                                headers=headers,
                            )
                        except Exception:
                            pass  # best-effort; never block the transcript
            transcript = " ".join(t for t in parts if t).strip()

            session.post(
                base_url + "/internal/transcript",
                json={
                    "id": row["id"],
                    "transcript": transcript,
                    "duration": duration,
                },
                headers=headers,
            )
        except Exception:
            log.exception("failed to transcribe voicemail %s", row.get("id"))
            continue
        finally:
            if tmp_path is not None and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    cfg = _env()
    model = load_model()  # constructed ONCE, before the loop
    session = requests.Session()

    while True:
        try:
            process_once(
                cfg["base_url"], model, session, auth_token=cfg["auth_token"]
            )
        except Exception:
            log.exception("poll cycle failed; retrying next interval")
        time.sleep(cfg["poll_interval"])


if __name__ == "__main__":
    main()
