# TASK: vm-status-cells

## Confirmed defect (observed, not suspected)

Confirmed by reading server.py: the front-page table's FTC and FCC cells are built by
`_mark_cell` (L638-650) as `{mark} <a ...>Report</a>` + a `toggle` button; the last
column is "Actions" (`<th>Actions</th>` in `_render_index` L670) built inline at
L701-708 as `<a ...>Report</a>` + a `Delete` button. Penn wants THREE clickable status
indicators -- FTC, FCC, TCPA -- each a red cross (glyph U+2717) when not filed and a
green check (glyph U+2713) when filed. The "Actions" column is DROPPED; TCPA replaces
it and Delete becomes a small control that rides on the row.

## Entry point

server.py: `init_db` migration tuple (L62-78), `_MARK_FLAGS` (L592), `api_list`
(L378-401), `_mark_cell` (L638-650), and `_render_index` header (L670) + per-row cells
(L699-708).

## Required change (server.py ONLY -- single-file app; the ALTER runs in init_db)

1. SCHEMA: add a `tcpa_filed` workflow flag, mirroring has_screenshots/ftc_filed/
   fcc_filed. In `init_db`, add `("tcpa_filed", "INTEGER DEFAULT 0"),` to the migration
   tuple that ALTERs missing columns in place (this covers both a fresh DB and an
   idempotent `ALTER TABLE voicemails ADD COLUMN tcpa_filed` on an existing DB).

2. WHITELIST: add `"tcpa_filed"` to `_MARK_FLAGS` so `POST /complaint/{id}/mark` accepts
   it (the same route/pattern FTC and FCC use).

3. api_list: add `tcpa_filed` to the SELECT column list AND to the returned dict
   (`"tcpa_filed": r["tcpa_filed"],`).

4. `_mark_cell(flag, vm_id_esc, set_flag)` (FTC/FCC): rewrite so that
   - `set_flag` falsy -> a CLICKABLE red cross (U+2717) linking to
     `/complaint/{id}/report`, styled `color:#c00`; NO green check (U+2713) in this state.
   - `set_flag` truthy -> a green check (U+2713) wrapped in `<span style="color:#080" ...>`;
     NO cross (U+2717) in this state.
   - BOTH states keep the toggle form posting to `/complaint/{id}/mark` with the hidden
     `flag` and a hidden `value` = the OPPOSITE of the current 0/1 state.

5. Add `def _tcpa_cell(vm_id_esc, set_flag):` -- a PURE MANUAL toggle (no report flow):
   - It is a single `<form method="post" action="/complaint/{id}/mark">` with hidden
     `<input name="flag" value="tcpa_filed">` and a hidden `<input name="value" ...>` set
     to the OPPOSITE of the current state, and a submit control that IS the glyph.
   - `set_flag` falsy -> the submit control shows a red cross (U+2717) styled `color:#c00`
     and its value posts 1 (mark filed); NO green check (U+2713).
   - `set_flag` truthy -> the submit control shows a green check (U+2713) styled
     `color:#080` and its value posts 0 (unmark); NO cross (U+2717).

6. Add `def _delete_cell(vm_id_esc):` returning a `<td>` with a small Delete control:
   `<form method="post" action="/delete/{id}" onsubmit="return confirm(...)">` with a
   submit button (a trash/Delete affordance).

7. `_render_index`:
   - HEADER: replace `<th>FTC</th><th>FCC</th><th>Actions</th>` with
     `<th>FTC</th><th>FCC</th><th>TCPA</th><th></th>` (TCPA plus a trailing cell for Delete).
   - PER-ROW: keep the two `_mark_cell(...)` appends for ftc_filed and fcc_filed; DELETE
     the inline Actions `<td>` (L701-708) and instead append
     `_tcpa_cell(vm_id_esc, it.get("tcpa_filed"))` then `_delete_cell(vm_id_esc)`.

Behaviour that must NOT change:
- FTC/FCC/TCPA all post flag + opposite-value to `/complaint/{id}/mark` (no new route).
- Delete still posts to `/delete/{id}`.
- `_render_index` still emits one `<tr>` per item; `vm_id_esc` is already escaped.

## Environment

- `DATA_DIR` (server.py L22): the DB location; the verify points it at a temp dir seeded
  with a legacy (pre-tcpa_filed) DB to exercise the ALTER migration.
- `AUTH_TOKEN` (server.py L21): left UNSET by the verify so `_check_auth` is open and the
  `/mark` round-trip needs no bearer.

## Must contain

- `_tcpa_cell`
- `_delete_cell`
- `tcpa_filed`
- `<th>TCPA</th>`
- `color:#c00`
- `color:#080`
- `/delete/`

## Scope

Only edit `server.py`; do not edit `verify.sh`, `test_fixture.py`, `check_literals.py`
or `TASK.md`.

## Keep every changed line exercised (relevance)

Color constants are asserted by check_literals; the three cells' glyph/link/toggle
behaviour, the `tcpa_filed` round-trip through `/mark` + `api_list`, the ALTER migration
on a legacy DB, the header change, and the Delete control are all asserted behaviourally
by test_fixture.py.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing until it prints `VERIFY_OK`.

## Note

For the TCPA cell the clickable glyph IS the form's submit control (the red
cross / green check button), so a single click posts the toggle to /mark -- there
is no separate report link for TCPA.
