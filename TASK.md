# TASK: voicemail-ui-s4-apilist

## Confirmed defect (observed, not suspected)

`GET /api/list` returns only the original ten keys (`id`, `created_at`,
`orig_name`, `status`, `transcript`, `duration_secs`, `caller_last4`,
`progress`, `callback_number`, `audio_url`). Verified by running the app and
inspecting a response body: rows that DO carry data in the newer columns
(`caller_number`, `is_spam`, `screenshot_paths`, `ov_vm`/`ov_shot`/`ov_ftc`/
`ov_fcc`/`ov_tcpa`) expose none of it through this endpoint, so the UI cannot
show caller number, spam flag, screenshot list, or any checkmark state.

## Entry point

server.py:378 (`def api_list()`, route `GET /api/list`)

## Environment

The test fixture sets `DATA_DIR` to an isolated temp directory *before* importing
`server.py` (server.py reads `DATA_DIR` / the DB path at import time). Honour the
existing `DATA_DIR`-based path resolution; do not hardcode a data directory.

## Required change

In api_list(), SELECT the new columns and add to each returned dict:
caller_number, is_spam (bool), screenshot_paths (parse the JSON TEXT to a list,
[] when NULL), and the five EFFECTIVE checkmark booleans vm/shot/ftc/fcc/tcpa
where each = COALESCE(ov_<field>, auto_<field>): auto_vm = (status=='done'),
auto_shot = bool(screenshot_ingested), auto_ftc=auto_fcc=auto_tcpa = False.

Exact contract for each item in the returned JSON array:
- `caller_number`: the stored value, or null when unset.
- `is_spam`: a real JSON boolean (true/false), not 0/1.
- `screenshot_paths`: the stored JSON text parsed to a list; `[]` when NULL.
- `vm`, `shot`, `ftc`, `fcc`, `tcpa`: real JSON booleans. Each is the override
  column (`ov_vm`, `ov_shot`, `ov_ftc`, `ov_fcc`, `ov_tcpa`) when that column
  is NOT NULL -- including an explicit 0, which must win over a true auto value
  (COALESCE semantics, not OR) -- otherwise the auto value: vm from
  status=='done', shot from screenshot_ingested being truthy, and ftc/fcc/tcpa
  always False.

Behaviour that must NOT change:
- The endpoint stays `GET /api/list`, takes no parameters, returns HTTP 200
  with a JSON array (empty table -> `[]`).
- Every pre-existing key keeps its name, value and meaning: id, created_at,
  orig_name, status, transcript, duration_secs, caller_last4, progress,
  callback_number, audio_url ("/audio/<id>").
- Ordering stays `ORDER BY created_at DESC`.
- No other route or table schema changes.

## Must contain

- `ov_vm`
- `screenshot_ingested`
- `"vm":`
- `"shot":`
- `"tcpa":`
- `"ftc":`
- `"fcc":`

(The gate holds the reference impl against this list. If the verify goes green
while one of these is absent from the changed files, the verify does not
enforce the spec -- that is a benign verify, caught mechanically.)

## Scope

Only edit `server.py`; do not edit `verify.sh`, `test_fixture.py` or `TASK.md`.
test_fixture.py is the test fixture -- changing it invalidates the check.

## Keep every changed line exercised (relevance)

After the job runs, a mutation check flips/deletes each line you changed and
asks the verify to catch it. A changed line whose every mutant survives --
because no test asserts it -- FAILS the gate even when the fix is correct, and
the review never runs. So do NOT emit an isolated, untested line:
- Fold an unavoidable constant onto a line the test already exercises. Put a
  `timeout=` / a `daemon=True` flag / a small tuning number on the SAME line as
  a header dict, URL, or argument the fixture checks -- never on its own line.
- Prefer falling through to an implicit `return None` over a standalone
  `return None` in an `except:` the tests do not assert.
- If a line genuinely cannot be asserted and cannot be folded, it usually
  should not be a separate line at all -- restructure so it isn't.
This is not about adding bogus assertions for constants; it is about not
leaving a lone line that carries no tested behaviour.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing until it prints
`VERIFY_OK`.
