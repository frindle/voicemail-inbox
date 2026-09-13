#!/usr/bin/env python3
"""Reference impl for: voicemail-ui-s4-apilist

The gate applies this, runs the verify, and reverts it. It proves two things at
once: the task is SATISFIABLE as specified, and the verify actually ENFORCES the
spec (a refimpl that goes green while a "Must contain" literal is absent means
the verify is benign).

Write the SIMPLEST change that makes the verify pass. It doubles as your review
reference when the model's diff comes back.
"""
import pathlib
import sys

wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = wt / 'server.py'
t = p.read_text()

OLD = """def api_list():
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, created_at, orig_name, status, transcript,"
            " duration_secs, caller_last4, progress, callback_number"
            " FROM voicemails ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"],
            "created_at": r["created_at"],
            "orig_name": r["orig_name"],
            "status": r["status"],
            "transcript": r["transcript"],
            "duration_secs": r["duration_secs"],
            "caller_last4": r["caller_last4"],
            "progress": r["progress"],
            "callback_number": r["callback_number"],
            "audio_url": "/audio/" + r["id"],
        }
        for r in rows
    ]"""

NEW = """def api_list():
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, created_at, orig_name, status, transcript,"
            " duration_secs, caller_last4, progress, callback_number,"
            " caller_number, is_spam, screenshot_paths, screenshot_ingested,"
            " ov_vm, ov_shot, ov_ftc, ov_fcc, ov_tcpa"
            " FROM voicemails ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()

    def _paths(raw):
        if not raw:
            return []
        return json.loads(raw)

    items = []
    for r in rows:
        auto_vm = r["status"] == "done"
        auto_shot = bool(r["screenshot_ingested"])
        item = {
            "id": r["id"],
            "created_at": r["created_at"],
            "orig_name": r["orig_name"],
            "status": r["status"],
            "transcript": r["transcript"],
            "duration_secs": r["duration_secs"],
            "caller_last4": r["caller_last4"],
            "progress": r["progress"],
            "callback_number": r["callback_number"],
            "audio_url": "/audio/" + r["id"],
            "caller_number": r["caller_number"],
            "is_spam": bool(r["is_spam"]),
            "screenshot_paths": _paths(r["screenshot_paths"]),
            "vm": bool(r["ov_vm"]) if r["ov_vm"] is not None else auto_vm,
            "shot": bool(r["ov_shot"]) if r["ov_shot"] is not None else auto_shot,
            "ftc": bool(r["ov_ftc"]) if r["ov_ftc"] is not None else False,
            "fcc": bool(r["ov_fcc"]) if r["ov_fcc"] is not None else False,
            "tcpa": bool(r["ov_tcpa"]) if r["ov_tcpa"] is not None else False,
        }
        items.append(item)
    return items"""

assert OLD in t, "refimpl anchor not found -- did the target change?"
p.write_text(t.replace(OLD, NEW, 1))
print("refimpl applied")
