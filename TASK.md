# TASK: voicemail-ui-s3-toggle

## Confirmed defect (observed, not suspected)

The UI has no way to toggle the per-voicemail compliance checkmarks. The
`/api/list` endpoint already exposes effective `vm`/`shot`/`ftc`/`fcc`/`tcpa`
flags computed as `COALESCE(ov_<field>, auto_<field>)`, and the schema already
carries the override columns (`ov_vm`, `ov_shot`, `ov_ftc`, `ov_fcc`,
`ov_tcpa`) -- but there is no route that writes them. Verified by reading
`server.py`: `init_db()` creates all five `ov_*` columns, `/api/list` reads
them, and a grep for any `UPDATE ... ov_` shows nothing ever sets one.

## Entry point

`server.py` -- the single-file FastAPI app; new route goes alongside the other
routes (e.g. after `/mark-spam`). Reuse `_check_auth`, `_db`, and the existing
effective-flag idiom from `/api/list` (`bool(auto) if ov is None else bool(ov)`).

Test environment: the fixture sets `$DATA_DIR` to an isolated temp directory
before importing the app; `server.py` already reads `DATA_DIR` for its sqlite
path, so no code change is needed for it -- it is named here only so the
fixture's environment is fully specified.

## Required change

Add `POST /checkmark/{vm_id}/{field}`, auth-gated via `_check_auth` (same
`authorization: str = Header(default=None)` pattern as the other gated routes;
401 `"unauthorized"` when a token is configured and missing/wrong).

Contract, exactly:
- `field` must be one of `vm`, `shot`, `ftc`, `fcc`, `tcpa`; anything else ->
  `HTTPException(status_code=400, detail="invalid field")`.
- Unknown `vm_id` -> `HTTPException(status_code=404, detail="unknown voicemail")`.
- Read the row's current EFFECTIVE value: `COALESCE(ov_<field>, auto_<field>)`,
  where `auto_vm = (status == 'done')`, `auto_shot = screenshot_ingested`, and
  `auto_ftc`/`auto_fcc`/`auto_tcpa` are all `0`.
- Flip that value and write the flipped value (1 or 0, never NULL) into
  `ov_<field>` for that row.
- Respond with JSON exactly `{"field": <field>, "value": true|false}` where
  `value` is the NEW state after the flip.

Behaviour that must NOT change:
- `/api/list` keeps reporting effective flags (`bool(auto) if ov is None else bool(ov)`).
- All existing routes (`/ingest`, `/internal/transcript`, `/mark-spam`, etc.) keep their status codes and bodies; auth semantics of `_check_auth` are unchanged (open access when `AUTH_TOKEN` is empty).

## Must contain

- `@app.post("/checkmark/{vm_id}/{field}")`
- `CHECKMARK_FIELDS = ("vm", "shot", "ftc", "fcc", "tcpa")`
- `"invalid field"`
- `"UPDATE voicemails SET ov_{} = ? WHERE id = ?".format(field)`
- `{"field": field, "value": bool(new_val)}`

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
- Prefer falling through to the implicit `return None` over a standalone
  `return None` in an `except:` the tests do not assert.
- If a line genuinely cannot be asserted and cannot be folded, it usually
  should not be a separate line at all -- restructure so it isn't.
This is not about adding bogus assertions for constants; it is about not
leaving a lone line that carries no tested behaviour.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing until it prints
`VERIFY_OK`.
