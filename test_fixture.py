#!/usr/bin/env python3
"""Adversarial behavioural fixture for the log-table index redesign.

Drives the REAL server.py in this worktree via fastapi.testclient. Rows are
seeded directly in a throwaway DB (fresh DATA_DIR) so per-case check-mark
counts are deterministic. A benign/partial implementation must fail here.
"""
import os
import sys
import tempfile

# Env parity: point the app at a throwaway DB and force OPEN auth BEFORE import
# (server.py reads DATA_DIR/AUTH_TOKEN at import time and runs init_db()).
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="ltidx-")
os.environ.pop("AUTH_TOKEN", None)

import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(server.app)
CK = "✓"       # the check-mark the table uses for a set status
DASH = "—"     # em-dash for an empty From/Callback

fails = 0
def check(cond, msg):
    global fails
    if cond:
        print("  ok:", msg)
    else:
        print("  FAIL:", msg); fails += 1

def wipe():
    conn = server._db()
    try:
        conn.execute("DELETE FROM voicemails"); conn.commit()
    finally:
        conn.close()

def add(vid, created_at, status="done", transcript=None, caller_number=None,
        callback_number=None, audio_path=None, duration_secs=None,
        progress=None, is_spam=0, has_screenshots=0, ftc_filed=0, fcc_filed=0,
        is_robocall=0, call_category="other", what_said_summary="hi",
        identifiability="none"):
    conn = server._db()
    try:
        conn.execute(
            "INSERT INTO voicemails (id, created_at, status, transcript,"
            " caller_number, callback_number, audio_path, duration_secs,"
            " progress, is_spam, has_screenshots, ftc_filed, fcc_filed,"
            " is_robocall, call_category, what_said_summary, identifiability)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (vid, created_at, status, transcript, caller_number,
             callback_number, audio_path, duration_secs, progress, is_spam,
             has_screenshots, ftc_filed, fcc_filed, is_robocall,
             call_category, what_said_summary, identifiability))
        conn.commit()
    finally:
        conn.close()

def col(vid, name):
    conn = server._db()
    try:
        r = conn.execute("SELECT %s AS v FROM voicemails WHERE id=?" % name,
                         (vid,)).fetchone()
        return r["v"] if r else None
    finally:
        conn.close()

def index_html():
    r = client.get("/")
    assert r.status_code == 200, r.status_code
    return r.text

# --- C1: table structure + header + poll kept -----------------------------
wipe()
add("h1", 1000, transcript="x", audio_path="/a.wav")
h = index_html()
check("<table" in h, "index renders an HTML <table>")
for colname in ("Date", "Time", "From", "Callback", "Recording",
                "Transcription", "Screenshots", "FTC", "FCC", "Actions"):
    check(colname in h, "header column present: " + colname)
check("setInterval" in h and "5000" in h, "5s poll/reload behaviour kept")

# --- C2: fully-done row -> rec+trans checks, From/Callback shown, no <audio>
wipe()
add("d1", 5000, status="done", transcript="hello world",
    caller_number="+17025550001", callback_number="+17025550002",
    audio_path="/rec.wav", progress=100, is_spam=1)
h = index_html()
check("+17025550001" in h, "done row shows From (caller_number)")
check("+17025550002" in h, "done row shows Callback number")
check(h.count(CK) == 2, "done row has exactly 2 check-marks (Recording+Transcription), got %d" % h.count(CK))
check("42%" not in h, "a done row shows no progress percent")
check("<audio" not in h, "index does NOT contain an <audio> player")

# --- C3: processing row -> progress %, not a check-mark --------------------
wipe()
add("p1", 6000, status="processing", transcript=None, progress=42,
    audio_path=None, caller_number=None, callback_number=None)
h = index_html()
check("42%" in h, "processing row shows the progress percent (42%)")
check(h.count(CK) == 0, "processing row shows no check-mark, got %d" % h.count(CK))
check(DASH in h, "empty From/Callback render as an em-dash")

# --- C4: detail page has audio + transcript -------------------------------
wipe()
add("det1", 7000, status="done", transcript="THE-TRANSCRIPT-TEXT",
    caller_number="+17025559999", audio_path="/d.wav")
r = client.get("/complaint/det1")
check(r.status_code == 200, "detail page 200")
check("<audio" in r.text and "/audio/det1" in r.text,
      "detail page renders the audio player")
check("THE-TRANSCRIPT-TEXT" in r.text, "detail page still shows the transcript")

# --- C5: report page bookmarklets intact ----------------------------------
r = client.get("/complaint/det1/report")
check(r.status_code == 200, "report page 200")
check("reportfraud.ftc.gov" in r.text, "report page keeps the FTC bookmarklet")
check("consumercomplaints.fcc.gov" in r.text, "report page keeps the FCC bookmarklet")

# --- C6: mark route drives FTC/FCC checks; bad flag rejected; 404 ----------
wipe()
add("m1", 8000, status="done", transcript="t", audio_path="/m.wav",
    ftc_filed=0, fcc_filed=0)
check(index_html().count(CK) == 2, "before marking: 2 checks (rec+trans)")
r = client.post("/complaint/m1/mark", data={"flag": "ftc_filed", "value": "1"})
check(r.status_code == 200 and r.json().get("ftc_filed") == 1, "POST /mark ftc_filed=1 ok")
check(index_html().count(CK) == 3, "after ftc mark: 3 checks")
r = client.post("/complaint/m1/mark", data={"flag": "fcc_filed", "value": "1"})
check(index_html().count(CK) == 4, "after fcc mark: 4 checks")
check(col("m1", "ftc_filed") == 1 and col("m1", "fcc_filed") == 1, "flags persisted in DB")
client.post("/complaint/m1/mark", data={"flag": "ftc_filed", "value": "0"})
check(index_html().count(CK) == 3, "after clearing ftc: back to 3 checks")
r = client.post("/complaint/m1/mark", data={"flag": "is_spam", "value": "1"})
check(r.status_code == 400, "POST /mark with a non-whitelisted flag is rejected (400)")
check(col("m1", "is_spam") == 0, "rejected flag did NOT mutate the row")
r = client.post("/complaint/NOPE/mark", data={"flag": "ftc_filed", "value": "1"})
check(r.status_code == 404, "POST /mark unknown id -> 404")

# --- C7: screenshots checkmark only after /ingest-screenshots -------------
wipe()
add("s1", 9000, status="done", transcript="t", audio_path="/s.wav",
    caller_number=None, duration_secs=30, has_screenshots=0)
check(index_html().count(CK) == 2, "before screenshots: 2 checks (rec+trans)")
ocr = "(702) 555-1234\n0:30\nToday 2:15 PM"
r = client.post("/ingest-screenshots", data={"ocr_text": ocr})
check(r.status_code == 200, "ingest-screenshots 200")
check(col("s1", "has_screenshots") == 1, "ingest set has_screenshots=1 on the matched row")
h = index_html()
check(h.count(CK) == 3, "after screenshots: 3 checks (rec+trans+screenshots), got %d" % h.count(CK))
check("+17025551234" in h, "matched caller_number surfaced")

# --- C8: newest-first ordering --------------------------------------------
wipe()
add("old", 1000, status="done", transcript="t", caller_number="+10000000001")
add("new", 2000, status="done", transcript="t", caller_number="+10000000002")
h = index_html()
check(h.index("+10000000002") < h.index("+10000000001"),
      "rows ordered newest-first by created_at")

print("--- %d failed ---" % fails)
sys.exit(1 if fails else 0)
