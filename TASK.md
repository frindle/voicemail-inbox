# TASK: voicemail-ui-s1-schema

## Confirmed defect (observed, not suspected)

The `voicemails` table has no screenshot-pipeline or manual-override columns.
Verified against a live database: `PRAGMA table_info(voicemails)` on
`data/voicemails.db` returns the v1/DNC schema only -- none of
`screenshot_ingested`, `screenshot_paths`, `ov_vm`, `ov_shot`, `ov_ftc`,
`ov_fcc`, `ov_tcpa` appear, so any code that wants to record an ingested
screenshot or manually override the auto-derived values has nowhere to store it.

## Entry point

server.py:37 -- `init_db()`, specifically its idempotent ADD COLUMN loop at
server.py:68-77 (the `for col, decl in (...)` block guarded by
`if col not in cols:`).

## Required change

In init_db()'s idempotent ADD COLUMN loop, add these columns (PRAGMA table_info
guard, same pattern as the existing loop): screenshot_ingested INTEGER DEFAULT 0,
screenshot_paths TEXT, ov_vm INTEGER, ov_shot INTEGER, ov_ftc INTEGER,
ov_fcc INTEGER, ov_tcpa INTEGER. The ov_* columns are nullable (NULL = use the
auto value; 0/1 = manual override).

Follow the existing loop's exact idiom: one `("column", "TYPE ...")` tuple per
line inside the same `for col, decl in (...)` list, relying on the existing
`if col not in cols:` guard and the shared
`ALTER TABLE voicemails ADD COLUMN {} {}` statement. Do not add a separate
migration block, do not touch CREATE TABLE, and do not change any other line of
the function.

Behaviour that must NOT change:
- init_db() stays idempotent: running it twice in a row (or on an already-migrated DB) raises nothing and leaves the schema unchanged.
- A legacy v1 database (only `id`, `created_at`, `orig_name`, `audio_path`, `status`, `transcript`, `duration_secs`) still migrates in place -- existing rows are preserved, never dropped or recreated.
- Every pre-existing column keeps its exact type and default (e.g. `is_spam INTEGER DEFAULT 0`), and the import-time `init_db()` call at module load still succeeds.

## Environment
- `DATA_DIR` — the fixture sets this to a temp dir before import; `server.py` reads it to locate the SQLite DB (`DB_PATH`). Do not hardcode a path.

## Must contain

- `screenshot_ingested`
- `screenshot_paths`
- `ov_vm`
- `ov_shot`
- `ov_ftc`
- `ov_fcc`
- `ov_tcpa`

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
