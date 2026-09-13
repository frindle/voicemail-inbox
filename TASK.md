# TASK: add the /set-caller endpoint to server.py

## Confirmed defect (observed, not suspected)

confirmed: `server.py` has no `/set-caller` route. A `POST /set-caller` against a
TestClient of the current app returns 404 (route not found). The iPhone Shortcut
needs an endpoint to attach a full caller phone number to a just-ingested
voicemail, matching the voicemail by its stored `caller_last4`.

## Entry point

`server.py` -- add ONE new route. A good place is right after the existing
`/delete/{vm_id}` route (around server.py:314), before `@app.get("/audio/{vm_id}")`.
Edit ONLY `server.py`.

## Required change

Add exactly this route (signature is fixed):

```python
@app.post("/set-caller")
def set_caller(caller_number: str = Form(default=None), caller_last4: str = Form(default=None)):
```

Behaviour, in order:
- Access-gated upstream by Cloudflare. DO NOT call `_check_auth` and DO NOT require
  a bearer token -- mirror the existing `/delete` route, which takes no auth.
  (`AUTH_TOKEN` may be set in the environment; `/set-caller` must still work with
  no `Authorization` header.)
- `num = (caller_number or "").strip()`. If not `num`, `raise HTTPException(status_code=400, detail="missing caller_number")`.
- Choose the match key source: `source = caller_last4 if caller_last4 and sum(c.isdigit() for c in caller_last4) >= 4 else num`.
  Then `last4 = "".join(ch for ch in source if ch.isdigit())[-4:]`.
- Open a connection with `_db()` (row_factory is `sqlite3.Row`). Wrap the body so
  the connection is ALWAYS closed in a `finally:`.
- Match an existing voicemail, preferring ones lacking a caller_number, newest first:
  ```sql
  SELECT id, caller_number FROM voicemails WHERE caller_last4 = ? ORDER BY (caller_number IS NULL) DESC, created_at DESC LIMIT 1
  ```
  with `(last4,)`. If a row is found, `matched = "last4"`.
- If no row matched, fall back to the newest voicemail overall:
  ```sql
  SELECT id, caller_number FROM voicemails ORDER BY created_at DESC LIMIT 1
  ```
  If a row is found here, `matched = "recent"`.
- If STILL no row, `raise HTTPException(status_code=404, detail="no voicemails")`.
- Update the matched row:
  ```sql
  UPDATE voicemails SET caller_number = ?, caller_last4 = COALESCE(caller_last4, ?) WHERE id = ?
  ```
  with `(num, last4, row_id)`, then `conn.commit()`.
- `return {"ok": True, "id": <matched row id>, "matched": matched}`.

`Form` and `RedirectResponse` are already imported. `_db()` already exists.
The columns `caller_number` and `caller_last4` already exist on the `voicemails`
table -- do NOT add a migration.

Behaviour that must NOT change:
- Every existing route stays exactly as-is. Do not touch `/ingest`, `/delete`,
  `_check_auth`, `init_db`, or any other function. Only ADD the new route.

## Must contain

- `/set-caller`
- `set_caller`
- `matched`
- `no voicemails`
- `COALESCE(caller_last4`

(The gate holds the reference impl against this list. If the verify goes green
while one of these is absent from the changed file, the verify does not enforce
the spec.)

## Environment (set by the verify/fixture, informational)

The verify stands the app up in isolation, so it sets these env vars -- your code
reads them exactly as the current app already does; do not change how they are read:
- `DATA_DIR` -- the app's data root (`os.environ["DATA_DIR"]`); the fixture points
  it at a fresh tempdir per case so no real data is touched.
- `AUTH_TOKEN` -- set non-empty by the fixture on purpose, to prove `/set-caller`
  works with NO `Authorization` header (it must NOT call `_check_auth`).

## Scope

Only edit `server.py`; do not edit `verify.sh`, `test_fixture.py` or `TASK.md`.
test_fixture.py is the test fixture -- changing it invalidates the check.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing until it prints
`VERIFY_OK`.
