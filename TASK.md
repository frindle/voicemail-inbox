# TASK: logtable-index — redesign GET / as a compact log table

## Confirmed defect (observed, not suspected)

Observed: `GET /` renders one CARD per voicemail — an `<audio>` player, the full
transcript, and a Report/Delete block — in `_render_index()` (server.py:579),
served by `index()` (server.py:641). Verified by reading those functions.
Penn wants a compact LOG TABLE instead: one `<tr>` per voicemail, audio +
transcript moved to the per-voicemail detail page, and workflow check-marks.

## Entry points

- `init_db()` server.py:37 — add guarded ALTER-if-missing columns.
- `api_list()` server.py:370 — must return the extra columns the table needs.
- `_render_index(items)` server.py:579 — rewrite to a table.
- `index()` server.py:641 — unchanged (feeds api_list() to _render_index).
- `complaint_page(vm_id)` server.py:504 — add the `<audio>` player here.
- `match_entries_to_voicemails()` server.py:1009 — set `has_screenshots=1` on
  the rows a screenshot links to (called by `/ingest-screenshots`, server.py:1051).
- NEW route: `POST /complaint/{vm_id}/mark`.

## Required change

1. `GET /` (via `_render_index`) returns an HTML `<table>` with a `<thead>`
   header row then one `<tr>` per voicemail, newest-first by `created_at DESC`
   (api_list already orders DESC). Columns IN THIS ORDER, with these exact
   header texts: **Date, Time, From, Callback, Recording, Transcription,
   Screenshots, FTC, FCC, Actions**.
   - Date: `YYYY-MM-DD` from `created_at` (epoch REAL) via `datetime`.
   - Time: `HH:MM` (24h) from `created_at`.
   - From: `caller_number`, or an em-dash `—` when empty.
   - Callback: `callback_number`, or `—` when empty.
   - Recording: the check-mark `✓` when `audio_path` is present, else blank.
   - Transcription: `✓` when `transcript` is non-empty AND `status == 'done'`;
     when `status == 'processing'` show the integer `progress` followed by `%`
     (e.g. `42%`) INSTEAD of a check-mark; else blank.
   - Screenshots: `✓` when `has_screenshots` is set, else blank.
   - FTC: a cell that BOTH links to `/complaint/{id}/report` AND has a clickable
     toggle — a `<form method="post" action="/complaint/{id}/mark">` with hidden
     `flag=ftc_filed` and `value=`(the opposite of the current 0/1) and a button
     labelled `toggle`; render `✓` iff `ftc_filed` is set.
   - FCC: same as FTC but `flag=fcc_filed`, also linking to `/complaint/{id}/report`.
   - Actions: a link to `/complaint/{id}/report` PLUS the existing Delete form
     (`method="post" action="/delete/{id}"`) — KEEP its `onsubmit` `confirm(...)`.
   - Use the check-mark character `✓` for every set status (do not use words).
2. REMOVE the `<audio>` player and the full transcript from the index. ADD an
   `<audio controls src="/audio/{id}"></audio>` to `complaint_page` (GET
   `/complaint/{id}`); its transcript block already renders there — keep it.
   `complaint_report_page` (GET `/complaint/{id}/report`) must keep BOTH
   bookmarklets — do NOT touch the autofill/bookmarklet logic.
3. Guarded ALTER-if-missing columns in `init_db()` (use the SAME PRAGMA
   `table_info(voicemails)` column-set gate already there):
   `has_screenshots INTEGER DEFAULT 0`, `ftc_filed INTEGER DEFAULT 0`,
   `fcc_filed INTEGER DEFAULT 0`.
4. `api_list()` must SELECT and return the columns the table needs that it does
   not already return: `caller_number`, `audio_path`, `has_screenshots`,
   `ftc_filed`, `fcc_filed` (keep every existing field — `/api/list` is also
   the 5s poll endpoint).
5. In the screenshot ingest path, set `has_screenshots=1` on the row(s) a
   screenshot links to (fold it into the existing UPDATE in
   `match_entries_to_voicemails`).
6. NEW route `POST /complaint/{vm_id}/mark` (function e.g. `complaint_mark`):
   call `_check_auth(authorization)` (bearer enforced iff AUTH_TOKEN set);
   `Form` fields `flag` and `value`; `flag` MUST be one of `ftc_filed` /
   `fcc_filed` — reject anything else with HTTP 400; coerce `value` to 0/1;
   `UPDATE` that column on the row; 404 on unknown id. It ONLY records human
   workflow state — it NEVER files or submits anything anywhere.
7. Keep the ~5s poll (`setInterval(refresh,5000)` -> `fetch('/api/list')` ->
   reload). Migrations must be safe on a LIVE SQLite file (guarded ALTER only);
   `_check_auth` semantics unchanged (OPEN when AUTH_TOKEN unset).

Behaviour that must NOT change:
- `_check_auth`: access is OPEN when the `AUTH_TOKEN` env var is unset.
- `/api/list` keeps all of its existing fields.
- `complaint_report_page` bookmarklets/prefill logic is untouched.

## Test harness / environment

`verify.sh` builds a `.venv` from `requirements.txt` and runs `test_fixture.py`,
which drives the app via `fastapi.testclient.TestClient`. The fixture sets the
env var **`DATA_DIR`** (a throwaway dir, so `init_db()` builds a fresh DB) and
ensures **`AUTH_TOKEN`** is UNSET (so `/complaint/{id}/mark` needs no bearer).
It seeds rows directly with `server._db()`.

## Must contain

- `<table`
- `<thead>`
- `Recording`
- `Screenshots`
- `Callback`
- `has_screenshots`
- `ftc_filed`
- `fcc_filed`
- `{vm_id}/mark`
- `toggle`
- `<audio`

## Scope

Only edit `server.py`; do NOT edit `verify.sh`, `test_fixture.py`,
`check_literals.py` or `TASK.md`.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing `server.py` until it
prints `VERIFY_OK`.
