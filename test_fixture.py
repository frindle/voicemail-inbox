"""Adversarial fixture for: voicemail-ui-s3-toggle

INTEGRATION fixture: drives the real FastAPI app through TestClient, asserting
status codes AND response bodies (plus DB state where persistence matters).

Cases separate "did the job" from "made the test go green":
  * effective-value semantics: COALESCE(ov_<field>, auto_<field>) with
    auto_vm = status=='done', auto_shot = screenshot_ingested, others 0
  * flip direction both ways (True->False and False->True) for every field
  * persistence: the flipped value is written into ov_<field> (not just echoed)
  * unhappy paths: invalid field -> 400 (not 500), unknown vm_id -> 404,
    missing/wrong bearer -> 401 when AUTH_TOKEN is configured
  * regression half: /api/list still reports the effective flags

Each case: (description, callable_returning_actual, expected)
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile

# Isolate BEFORE server.py runs init_db() at import time.
_tmp = tempfile.mkdtemp(prefix="checkmark-fixture-")
os.environ["DATA_DIR"] = _tmp

spec = importlib.util.spec_from_file_location("target", 'server.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)

from fastapi.testclient import TestClient  # noqa: E402

client = TestClient(target.app)


def _conn():
    return sqlite3.connect(os.path.join(_tmp, "voicemails.db"))


def _seed(vm_id, status="processing", screenshot_ingested=0):
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO voicemails (id, created_at, orig_name, audio_path,"
            " status, screenshot_ingested)"
            " VALUES (?, 0.0, 'a.wav', '/x/a.wav', ?, ?)",
            (vm_id, status, screenshot_ingested),
        )
        conn.commit()
    finally:
        conn.close()


def _ov(vm_id):
    """(ov_vm, ov_shot, ov_ftc, ov_fcc, ov_tcpa) for a row."""
    conn = _conn()
    try:
        return conn.execute(
            "SELECT ov_vm, ov_shot, ov_ftc, ov_fcc, ov_tcpa FROM voicemails"
            " WHERE id = ?", (vm_id,),
        ).fetchone()
    finally:
        conn.close()


def _with_auth(headers):
    """Run one request with AUTH_TOKEN configured; restore afterwards."""
    old = target.AUTH_TOKEN
    target.AUTH_TOKEN = "sekret"
    try:
        r = client.post("/checkmark/vmA/ftc", headers=headers)
    finally:
        target.AUTH_TOKEN = old
    return (r.status_code, r.json().get("detail"))


_seed("vmA", status="done")  # auto vm=True; shot/ftc/fcc/tcpa auto False
_seed("vmB", status="processing", screenshot_ingested=1)  # auto shot=True

CASES = [
    ("vm flips OFF when effective is True via status='done' (ov_vm NULL)",
     lambda: client.post("/checkmark/vmA/vm").json(),
     {"field": "vm", "value": False}),
    ("second flip turns vm back ON and persists ov_vm=1 in the DB",
     lambda: (client.post("/checkmark/vmA/vm").json()["value"], _ov("vmA")[0]),
     (True, 1)),
    ("shot flips OFF when screenshot_ingested=1 and ov_shot is NULL",
     lambda: client.post("/checkmark/vmB/shot").json(),
     {"field": "shot", "value": False}),
    ("ftc flips ON from auto 0 and persists ov_ftc=1",
     lambda: (client.post("/checkmark/vmA/ftc").json()["value"], _ov("vmA")[2]),
     (True, 1)),
    ("fcc and tcpa both flip ON from auto 0",
     lambda: tuple(client.post("/checkmark/vmB/" + f).json()["value"]
                   for f in ("fcc", "tcpa")),
     (True, True)),
    ("invalid field -> 400 with detail 'invalid field', not a 500",
     lambda: (lambda r: (r.status_code, r.json().get("detail")))(
         client.post("/checkmark/vmA/bogus")),
     (400, "invalid field")),
    ("unknown vm_id -> 404 with detail 'unknown voicemail'",
     lambda: (lambda r: (r.status_code, r.json().get("detail")))(
         client.post("/checkmark/nope/vm")),
     (404, "unknown voicemail")),
    ("no bearer token -> 401 unauthorized when AUTH_TOKEN is configured",
     lambda: _with_auth({}),
     (401, "unauthorized")),
    ("wrong bearer -> 401; correct bearer -> 200 and the flip happens",
     lambda: (_with_auth({"Authorization": "Bearer wrong"})[0],
              _with_auth({"Authorization": "Bearer sekret"})[0]),
     (401, 200)),
    ("regression: /api/list still reports effective vm/shot flags",
     lambda: {i["id"]: (i["vm"], i["shot"])
              for i in client.get("/api/list").json()},
     {"vmA": (True, False), "vmB": (False, False)}),
]


def main():
    if len(CASES) < 3:
        print("  SCAFFOLD_INCOMPLETE: {} adversarial case(s) authored, need >= 3."
              .format(len(CASES)))
        print("  A generated scaffold is not a verify. Author the cases in "
              "test_fixture.py.")
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
