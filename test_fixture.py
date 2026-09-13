"""Adversarial integration fixture for the /set-caller endpoint.

Each case stands up a FRESH FastAPI app in its own isolated DATA_DIR (so no real
data is touched), seeds voicemail rows directly into that app's SQLite DB, drives
POST /set-caller through a TestClient, and asserts BOTH the HTTP response and the
resulting DB state. AUTH_TOKEN is set non-empty on purpose: /set-caller must work
with NO Authorization header (it is Cloudflare-gated, not bearer-gated). We assert
ONLY /set-caller behaviour -- never other routes' auth.

Each case: (description, callable_returning_actual, expected).
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile

REPO = os.path.dirname(os.path.abspath(__file__))
_counter = [0]


def load_app(datadir):
    """Load server.py fresh with DATA_DIR pointed at an isolated tempdir and
    AUTH_TOKEN set non-empty. A fresh module object per call so route
    registration and DB path re-run under the current env."""
    os.environ["DATA_DIR"] = datadir
    os.environ["AUTH_TOKEN"] = "unit-test-secret"
    _counter[0] += 1
    modname = "target_server_%d" % _counter[0]
    spec = importlib.util.spec_from_file_location(
        modname, os.path.join(REPO, "server.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[modname] = mod
    spec.loader.exec_module(mod)
    return mod


def seed(mod, rows):
    """rows: list of dicts with keys id, created_at, caller_number, caller_last4."""
    conn = mod._db()
    try:
        for r in rows:
            conn.execute(
                "INSERT INTO voicemails (id, created_at, caller_number, caller_last4)"
                " VALUES (?, ?, ?, ?)",
                (r["id"], r["created_at"], r.get("caller_number"),
                 r.get("caller_last4")))
        conn.commit()
    finally:
        conn.close()


def db_row(mod, vm_id):
    conn = mod._db()
    try:
        r = conn.execute(
            "SELECT caller_number, caller_last4 FROM voicemails WHERE id = ?",
            (vm_id,)).fetchone()
    finally:
        conn.close()
    return (None if r is None else (r["caller_number"], r["caller_last4"]))


def client_for(rows):
    from fastapi.testclient import TestClient
    d = tempfile.mkdtemp(prefix="setcaller-")
    mod = load_app(d)
    if rows:
        seed(mod, rows)
    return mod, TestClient(mod.app)


def case_last4_match_prefers_null_number():
    """last4 match: two rows share caller_last4='9244'. One already HAS a
    caller_number (newer); one has NULL (older). The ORDER BY prefers the NULL
    one despite being older. Posting the full number tags THAT row and leaves
    the already-numbered row untouched. Proves 200 + matched='last4' + the
    (caller_number IS NULL) DESC ordering + the number is written."""
    mod, c = client_for([
        {"id": "hasnum", "created_at": 200.0,
         "caller_number": "999-999-9999", "caller_last4": "9244"},
        {"id": "nonum", "created_at": 100.0,
         "caller_number": None, "caller_last4": "9244"},
    ])
    r = c.post("/set-caller", data={"caller_number": "830-457-9244"})
    body = r.json() if r.status_code == 200 else {}
    return (r.status_code, body.get("matched"), body.get("id"),
            db_row(mod, "nonum"), db_row(mod, "hasnum"))


def case_fallback_recent_and_coalesce():
    """No caller_last4 matches the posted number's last4 (1234), so it falls
    back to the NEWEST row overall (matched='recent'). Also the matched row
    already had caller_last4='0000': COALESCE must KEEP '0000', not overwrite it
    with the new last4 '1234'. Proves the fallback branch AND COALESCE(caller_last4,?)."""
    mod, c = client_for([
        {"id": "old", "created_at": 100.0,
         "caller_number": None, "caller_last4": "5555"},
        {"id": "new", "created_at": 300.0,
         "caller_number": None, "caller_last4": "0000"},
    ])
    r = c.post("/set-caller", data={"caller_number": "512-555-1234"})
    body = r.json() if r.status_code == 200 else {}
    return (r.status_code, body.get("matched"), body.get("id"),
            db_row(mod, "new"))


def case_empty_caller_number_400():
    """Empty caller_number -> 400. A row exists, so this must NOT be a 404: the
    guard is about the missing number, not about missing voicemails."""
    mod, c = client_for([
        {"id": "x", "created_at": 100.0,
         "caller_number": None, "caller_last4": "1234"},
    ])
    r = c.post("/set-caller", data={"caller_number": ""})
    return r.status_code


def case_no_voicemails_404():
    """Empty DB -> 404 with detail 'no voicemails'."""
    mod, c = client_for([])
    r = c.post("/set-caller", data={"caller_number": "512-555-1234"})
    detail = None
    try:
        detail = r.json().get("detail")
    except Exception:
        pass
    return (r.status_code, detail)


def case_caller_last4_override_takes_precedence():
    """caller_last4 with >= 4 digits OVERRIDES caller_number as the match key.
    Row A has caller_last4='1234' (matches the posted number's last4). Row B has
    caller_last4='9999' (matches the explicit caller_last4 override). Posting
    caller_number='555-111-1234' (last4=1234) WITH caller_last4='9999' must match
    Row B, not Row A -- and write the full number onto Row B. A '>= 5' mutation
    of the digit threshold would fail to override and tag Row A instead."""
    mod, c = client_for([
        {"id": "A", "created_at": 300.0,
         "caller_number": None, "caller_last4": "1234"},
        {"id": "B", "created_at": 100.0,
         "caller_number": None, "caller_last4": "9999"},
    ])
    r = c.post("/set-caller",
               data={"caller_number": "555-111-1234", "caller_last4": "9999"})
    body = r.json() if r.status_code == 200 else {}
    return (r.status_code, body.get("matched"), body.get("id"),
            db_row(mod, "A"), db_row(mod, "B"))


CASES = [
    ("last4 match prefers the null-caller_number row and writes the number",
     case_last4_match_prefers_null_number,
     (200, "last4", "nonum", ("830-457-9244", "9244"), ("999-999-9999", "9244"))),
    ("no last4 match -> fall back to newest (matched='recent'), COALESCE keeps caller_last4",
     case_fallback_recent_and_coalesce,
     (200, "recent", "new", ("512-555-1234", "0000"))),
    ("empty caller_number -> 400 (not 404, a row exists)",
     case_empty_caller_number_400,
     400),
    ("no voicemails at all -> 404 detail 'no voicemails'",
     case_no_voicemails_404,
     (404, "no voicemails")),
    ("caller_last4 override (>=4 digits) beats caller_number as the match key",
     case_caller_last4_override_takes_precedence,
     (200, "last4", "B", (None, "1234"), ("555-111-1234", "9999"))),
]


def main():
    if len(CASES) < 3:
        print("  SCAFFOLD_INCOMPLETE: %d case(s), need >= 3." % len(CASES))
        return 1
    fails = 0
    for desc, thunk, want in CASES:
        try:
            got = thunk()
        except Exception as e:
            import traceback
            print("  FAIL %s -- raised %s: %s" % (desc, type(e).__name__, e))
            traceback.print_exc()
            fails += 1
            continue
        if got != want:
            print("  FAIL %s\n       got  %r\n       want %r" % (desc, got, want))
            fails += 1
        else:
            print("  ok   %s" % desc)
    print("  %d/%d case(s) passed" % (len(CASES) - fails, len(CASES)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
