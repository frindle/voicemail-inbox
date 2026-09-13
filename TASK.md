# TASK: ingest-screenshots

Add a new endpoint `POST /ingest-screenshots` to `server.py` that takes OCR
text from iPhone screenshots (a carrier Visual-Voicemail list and/or the native
Recents / Call-History screen), extracts the caller phone numbers, and writes
each number onto the matching voicemail row — the number Visual Voicemail never
exposes to a Shortcut.

**Only edit `server.py`.** Do NOT edit `verify.sh`, `test_fixture.py`,
`check_literals.py`, or `refimpl.py`. Run `bash verify.sh` after every edit and
fix the named FAILs until it prints `VERIFY_OK`.

## Confirmed defect (observed, not suspected)
Visual Voicemail does not expose the sender number to a Shortcut, so voicemail
rows land with `caller_number` NULL. But the carrier VM-list screenshot and the
Recents screenshot BOTH show the number as on-screen text, so on-device OCR
("Get Text from Image") can recover it — this endpoint receives that OCR text
and back-fills the number.

## Context (confirmed by reading the code)
- `server.py` is a single-file FastAPI app. DB helper `_db()` uses `sqlite3`
  with `row_factory = sqlite3.Row`. The app object is `app`. `Form`, `Header`,
  `HTTPException` are already imported.
- Table `voicemails` already has: `id TEXT`, `created_at REAL` (unix time set at
  UPLOAD, NOT call time), `duration_secs REAL` (audio length from Whisper, may
  be NULL until transcribed), `caller_number TEXT`, `caller_last4 TEXT`.
- The existing sibling `POST /set-caller` (search for `def set_caller`) shows the
  house style: last-4 normalisation, `_db()` usage, no bearer (Cloudflare-gated).

## Why duration is the match key (not clock time)
`created_at` is the UPLOAD time, so it does NOT line up with the clock time in a
screenshot. The reliable join is **duration**: the app shows a voicemail's length
as `M:SS` (e.g. `0:50`) and `duration_secs` holds the same length in seconds.
Clock time is used ONLY to order/break ties, never as an absolute match.

## Endpoint contract
`@app.post("/ingest-screenshots")` accepting `multipart/form-data`:
- `ocr_text: str = Form(default=None)` — the concatenated "Get Text from Image"
  output of one or more screenshots. If missing/blank →
  `raise HTTPException(status_code=400, detail="missing ocr_text")`.

Returns JSON:
```
{"matched": [{"id": <vm_id>, "number": "+1XXXXXXXXXX", "last4": "5333",
              "by": "duration" | "order"}, ...],
 "unmatched": ["+1XXXXXXXXXX", ...]}
```

## Parsing `ocr_text` (e.g. a helper `parse_screenshot_ocr(text) -> list[dict]`)
Return entries in first-seen order, each:
`{"digits": "8446315333", "last4": "5333", "number": "+18446315333", "duration": 50 | None}`

1. **Phone formats seen in the real OCR** (recognise all three):
   `+18446315333`, `+1 (844) 631-5333`, `(844) 631-5333`. Normalise to digits,
   drop a leading country-code `1` if that leaves 11 digits, keep the last 10 →
   `digits`; `last4 = digits[-4:]`; `number = "+1" + digits`. A candidate needs
   exactly 10 digits after normalisation — ignore shorter runs (nav labels,
   the status-bar clock `19:00`, etc.).
2. **One entry per distinct number**, first-seen order (a Recents contact card
   repeats the number — dedupe; if a later duplicate carries a duration and the
   first did not, keep that duration).
3. **Duration vs clock within a number's block.** A time-like token is
   `\d{1,2}:\d{2}`. The lines from a phone line up to the next phone line are
   that number's block. Split the block at a **date marker** — a line that is
   `Today`/`Yesterday`, starts with `Today`/`Yesterday`, or is a weekday/date.
   A time-like token **before** the marker is the **duration** (`M:SS` →
   `minutes*60 + seconds`). A time-like token **after** the marker (or embedded
   in a `Today · 16:14` marker line) is the clock time and is NOT the duration.
   Duration is `None` when there is no pre-marker time token (the Recents /
   Call-History screens carry only a clock time — `16:14` must NOT be read as a
   duration).
4. Noise lines are simply not phone lines: `unknown`, `Missed`, `Missed Call`,
   `Incoming Call`, `Mark as Known`, `Delete`, `Add Name`, `Share Contact`,
   `Call History`, `All voicemails are encrypted`, nav bars, etc.

## Matching (e.g. `match_entries_to_voicemails(entries) -> (matched, unmatched)`)
- Candidate rows = voicemails with `caller_number IS NULL`, ordered
  `created_at DESC`. Track ids claimed in THIS request so two entries never map
  to the same row.
- If the entry has a `duration`, prefer the first unclaimed candidate whose
  `duration_secs` is within 2s (`abs(duration_secs - duration) <= 2`) →
  `by = "duration"`. A candidate with `duration_secs` NULL can never match this
  way.
- Otherwise (no duration, or none within tolerance) take the first unclaimed
  candidate in `created_at DESC` order → `by = "order"`.
- On a match: `UPDATE voicemails SET caller_number = ?,
  caller_last4 = COALESCE(caller_last4, ?) WHERE id = ?`, append to `matched`.
  If no candidate remains, append the number to `unmatched`.

## Must contain
- `/ingest-screenshots`
- `ocr_text`
- `caller_number IS NULL`
- `created_at DESC`
- `COALESCE`
- `"by"`
- `"duration"`
- `"order"`

## Loop instruction
Run `bash verify.sh` after every edit; fix each named FAIL until it prints
`VERIFY_OK`. Only edit `server.py`; do not edit the harness files.
