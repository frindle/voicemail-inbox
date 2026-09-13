"""Adversarial fixture for: ingest-screenshots

Drives the REAL endpoint POST /ingest-screenshots via FastAPI's TestClient
against a seeded temp DB, so it tests observable behaviour regardless of how the
implementation names its internal helpers. OCR strings are taken from the actual
iPhone screenshots (carrier Visual-Voicemail list + native Recents/Call-History).

Each case: (description, callable_returning_actual, expected).
"""
import os
import sys
import tempfile
import importlib.util

# Isolate the DB BEFORE importing server (init_db runs at import).
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="vm-fixture-")

spec = importlib.util.spec_from_file_location("target", 'server.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(target.app)


def _reset(rows):
    """rows = list of (id, created_at, duration_secs, caller_number). Replace
    the whole voicemails table with exactly these."""
    conn = target._db()
    try:
        conn.execute("DELETE FROM voicemails")
        for vid, created, dur, num in rows:
            conn.execute(
                "INSERT INTO voicemails (id, created_at, status, duration_secs, caller_number)"
                " VALUES (?, ?, 'done', ?, ?)",
                (vid, created, dur, num),
            )
        conn.commit()
    finally:
        conn.close()


def _num(vid):
    conn = target._db()
    try:
        r = conn.execute("SELECT caller_number, caller_last4 FROM voicemails WHERE id=?",
                         (vid,)).fetchone()
        return (r["caller_number"], r["caller_last4"]) if r else (None, None)
    finally:
        conn.close()


# Real OCR text (carrier Visual-Voicemail list, image 3): number / duration /
# "Today" / clock-time per row.
VM_APP_TWO = (
    "Voicemail\nON\n"
    "(844) 631-5333\n0:50\nToday\n16:14\n"
    "(855) 806-0602\n0:23\nToday\n11:29\n"
    "All voicemails are encrypted\n"
    "Home Messages Voicemail Account Support\n"
)

# Both voicemails 0:50 (duration collision) -> must fall back to created_at order.
VM_APP_COLLIDE = (
    "Voicemail\nON\n"
    "(844) 631-5333\n0:50\nToday\n16:14\n"
    "(855) 806-0602\n0:50\nToday\n11:29\n"
    "All voicemails are encrypted\n"
)

# Native Recents / Call-History (images 1/2/4): number + clock-time, NO duration.
RECENTS_ONE = (
    "19:00\n+1 (844) 631-5333\nCall History\nMissed Call\nToday · 16:14\n"
    "Add Name\nphone RECENT\n+1 (844) 631-5333\nShare Contact\n"
)

# E.164 form (image 1 header).
E164_ONE = "19:00\n+18446315333\nCall History\nIncoming Call\nMissed\nToday · 16:14\n"

NOISE_ONLY = ("Unknown Callers\nSearch\nunknown\nMark as Known\nDelete\n"
              "All voicemails are encrypted\nFavorites Recents Contacts Keypad Voicemail\n")


def case_two_distinct_durations():
    # rows: one 50s, one 23s, both numberless -> matched by duration.
    _reset([("A", 100.0, 50.0, None), ("B", 200.0, 23.0, None)])
    r = client.post("/ingest-screenshots", data={"ocr_text": VM_APP_TWO})
    if r.status_code != 200:
        return ("HTTP", r.status_code)
    a = _num("A")[0]   # should be the 0:50 caller
    b = _num("B")[0]   # should be the 0:23 caller
    return (a, b)


def case_duration_collision_falls_to_order():
    # both 50s; created_at B(200) newer than A(100). Entries in OCR order:
    # 844 first, 855 second. Newest row (B) -> first entry (844); A -> 855.
    _reset([("A", 100.0, 50.0, None), ("B", 200.0, 50.0, None)])
    r = client.post("/ingest-screenshots", data={"ocr_text": VM_APP_COLLIDE})
    if r.status_code != 200:
        return ("HTTP", r.status_code)
    return (_num("B")[0], _num("A")[0])


def case_clock_not_treated_as_duration():
    # Recents has NO duration, only "Today . 16:14". A buggy parser that reads
    # 16:14 as a duration = 974s would match by="duration" against this row
    # (duration_secs 974). The correct parser sees no duration -> matches by
    # ORDER. Assert the match reason is "order", proving 16:14 wasn't a duration.
    _reset([("A", 100.0, 974.0, None)])
    r = client.post("/ingest-screenshots", data={"ocr_text": RECENTS_ONE})
    if r.status_code != 200:
        return ("HTTP", r.status_code)
    body = r.json()
    m = body.get("matched") or []
    by = m[0].get("by") if m else None
    return (_num("A")[1], by)   # (last4, match-reason)


def case_e164_format():
    _reset([("A", 100.0, 30.0, None)])
    r = client.post("/ingest-screenshots", data={"ocr_text": E164_ONE})
    if r.status_code != 200:
        return ("HTTP", r.status_code)
    return _num("A")   # (caller_number, caller_last4)


def case_missing_ocr_text_400():
    _reset([("A", 100.0, 30.0, None)])
    r = client.post("/ingest-screenshots", data={})
    return r.status_code


def case_does_not_overwrite_existing():
    # A already has a number; B is numberless. The single OCR'd number must land
    # on B (caller_number IS NULL), never overwrite A.
    _reset([("A", 200.0, 30.0, "+19999999999"), ("B", 100.0, 30.0, None)])
    r = client.post("/ingest-screenshots", data={"ocr_text": E164_ONE})
    if r.status_code != 200:
        return ("HTTP", r.status_code)
    return (_num("A")[0], _num("B")[0])


def case_noise_only_no_crash():
    _reset([("A", 100.0, 30.0, None)])
    r = client.post("/ingest-screenshots", data={"ocr_text": NOISE_ONLY})
    if r.status_code != 200:
        return ("HTTP", r.status_code)
    body = r.json()
    return (body.get("matched"), _num("A")[0])


CASES = [
    # 1. THE POSITIVE CASE -- the thing the fix is supposed to start doing.
    ("two distinct durations -> matched by duration",
     case_two_distinct_durations, ("+18446315333", "+18558060602")),
    # 2. BOUNDARY (tolerance <= 2s): exactly AT the edge must still be "duration".
    ("duration diff exactly 2s -> within tolerance, by=duration",
     lambda: (lambda r: (r.json()["matched"][0]["by"], _num("A")[0]))(
         client.post("/ingest-screenshots", data={"ocr_text": VM_APP_TWO}))
         if (_reset([("A", 100.0, 52.0, None)]), True)[1] else None,
     ("duration", "+18446315333")),
    # 3. BOUNDARY: just PAST the edge (diff 3s) must fall back to "order".
    ("duration diff 3s -> outside tolerance, by=order fallback",
     lambda: (lambda r: (r.json()["matched"][0]["by"], _num("A")[0]))(
         client.post("/ingest-screenshots", data={"ocr_text": VM_APP_TWO}))
         if (_reset([("A", 100.0, 53.0, None)]), True)[1] else None,
     ("order", "+18446315333")),
    # 4. OVER-BROADENING CONTROL: clock time after the date marker is NOT a duration.
    ("clock time 16:14 is NOT parsed as a duration (match reason = order)",
     case_clock_not_treated_as_duration, ("5333", "order")),
    # 5. OVER-BROADENING CONTROL: status-bar clock 19:00 (=1140s) is not a duration either.
    ("status-bar clock 19:00 NOT read as a 1140s duration (by=order)",
     lambda: (lambda r: (_num("A")[1], r.json()["matched"][0]["by"]))(
         client.post("/ingest-screenshots", data={"ocr_text": E164_ONE}))
         if (_reset([("A", 100.0, 1140.0, None)]), True)[1] else None,
     ("5333", "order")),
    # 6. AMBIGUITY / ZERO CANDIDATES: second number has no row left -> unmatched, not a guess.
    ("two numbers, one NULL row -> first claims it, second goes to unmatched",
     lambda: (lambda r: (_num("A")[0], r.json()["unmatched"]))(
         client.post("/ingest-screenshots", data={"ocr_text": VM_APP_TWO}))
         if (_reset([("A", 100.0, 30.0, None)]), True)[1] else None,
     ("+18446315333", ["+18558060602"])),
    # 7. SAFETY: repeated number in Recents dedupes -> exactly one match, unmatched empty.
    ("repeated number in Recents OCR -> one entry, unmatched stays empty",
     lambda: (lambda r: (len(r.json()["matched"]), r.json()["unmatched"], _num("A")[0]))(
         client.post("/ingest-screenshots", data={"ocr_text": RECENTS_ONE}))
         if (_reset([("A", 100.0, 30.0, None)]), True)[1] else None,
     (1, [], "+18446315333")),
    # 8. DEGENERATE INPUT: blank ocr_text must be a clean 400, not a silent 200.
    ("blank/whitespace ocr_text -> HTTP 400",
     lambda: client.post("/ingest-screenshots", data={"ocr_text": "   \n"}).status_code,
     400),
    # 9. DEGENERATE INPUT: missing key must be a clean 400 (not 500, not 200).
    ("missing ocr_text -> HTTP 400",
     case_missing_ocr_text_400, 400),
    # 10. SAFETY / NO-EVIDENCE: never overwrite an existing caller_number.
    ("never overwrites an existing caller_number (only NULL rows)",
     case_does_not_overwrite_existing, ("+19999999999", "+18446315333")),
    # 11. SAFETY / NO-EVIDENCE: noise-only OCR -> do nothing, no crash.
    ("noise-only OCR -> no match, no crash, existing row untouched",
     case_noise_only_no_crash, ([], None)),
    # 12. OVER-BROADENING CONTROL: short digit runs are not phone numbers.
    ("short digit runs (5333/631) are NOT phone candidates -> nothing claimed",
     lambda: (lambda r: (r.json()["matched"], r.json()["unmatched"], _num("A")[0]))(
         client.post("/ingest-screenshots", data={"ocr_text": "5333\n631\n844\n19:00\n"}))
         if (_reset([("A", 100.0, 30.0, None)]), True)[1] else None,
     ([], [], None)),
    # 13. IDEMPOTENCE / PRESERVATION: re-posting the same OCR is a no-op that keeps the number.
    ("second identical post -> no NULL rows left, matched empty, number preserved",
     lambda: (lambda r2: (_num("A")[0], r2.json()["matched"], r2.json()["unmatched"]))(
         client.post("/ingest-screenshots", data={"ocr_text": E164_ONE}))
         if (_reset([("A", 100.0, 30.0, None)]),
             client.post("/ingest-screenshots", data={"ocr_text": E164_ONE}), True)[2] else None,
     ("+18446315333", [], ["+18446315333"])),
    # 14. REGRESSION HALF: pre-existing endpoint must keep working after the change.
    ("regression: GET /healthz still returns {status: ok}",
     lambda: client.get("/healthz").json(), {"status": "ok"}),
]


def main():
    if len(CASES) < 3:
        print("  SCAFFOLD_INCOMPLETE: need >= 3 cases")
        return 1
    fails = 0
    for desc, thunk, want in CASES:
        try:
            got = thunk()
        except Exception as e:
            print("  FAIL {} -- raised {}: {}".format(desc, type(e).__name__, e))
            fails += 1
            continue
        if got != want:
            print("  FAIL {} -- got {!r}, want {!r}".format(desc, got, want))
            fails += 1
    print("  {}/{} case(s) passed".format(len(CASES) - fails, len(CASES)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
