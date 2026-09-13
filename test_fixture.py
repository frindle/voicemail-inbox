"""Adversarial fixture for: voicemail-ui-s4-apilist

>>> THE ONE THING THE GENERATOR CANNOT WRITE FOR YOU <<<

CASES is empty and the verify FAILS until you fill it in. That is deliberate.
A generator can emit a verify that DISCRIMINATES (fails at baseline, passes on
a fix). It cannot decide whether the verify is RELEVANT -- whether it tests the
property the task actually asked for. A benign case passes broken work.

Pick inputs that separate "did the job" from "made the test go green":
  * the exact boundary the defect is about, and one on each side of it
  * the degenerate inputs (missing key, None, empty, wrong type) that must NOT
    raise
  * at least one case that a plausible WRONG fix would fail
  * the regression half: things that already work and must keep working

Each case: (description, callable_returning_actual, expected)
"""
import json
import os
import sys
import tempfile
import time
import uuid
import importlib.util

# Isolate the app's SQLite DB in a throwaway dir BEFORE server.py is imported
# (DATA_DIR / DB_PATH are read at import time), so cases never touch real data.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="vmfix_")

spec = importlib.util.spec_from_file_location("target", 'server.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


def _client():
    from fastapi.testclient import TestClient
    return TestClient(target.app)


def _seed(**kw):
    vm_id = "fix_" + uuid.uuid4().hex[:10]
    row = {
        "created_at": time.time(),
        "orig_name": "shared.wav",
        "audio_path": "/tmp/shared.wav",
        "status": "pending",
        "transcript": None,
        "duration_secs": 2.5,
        "caller_number": None,
        "is_spam": 0,
        "screenshot_paths": None,
        "screenshot_ingested": 0,
        "ov_vm": None,
        "ov_shot": None,
        "ov_ftc": None,
        "ov_fcc": None,
        "ov_tcpa": None,
    }
    row.update(kw)
    conn = target._db()
    try:
        cols = ", ".join(["id"] + list(row))
        ph = ", ".join("?" * (len(row) + 1))
        conn.execute(
            "INSERT INTO voicemails ({}) VALUES ({})".format(cols, ph),
            [vm_id] + list(row.values()),
        )
        conn.commit()
    finally:
        conn.close()
    return vm_id


def _item(vm_id):
    resp = _client().get("/api/list")
    assert resp.status_code == 200, "GET /api/list -> {}".format(resp.status_code)
    for it in resp.json():
        if it.get("id") == vm_id:
            return it
    raise AssertionError("seeded row {} missing from /api/list".format(vm_id))


def _b(v):
    """(is-True, is-False, is-a-real-bool) probe so an int 1/0 cannot
    masquerade as a boolean through the JSON boundary."""
    return (v == True, v == False, type(v) is bool)  # noqa: E712


CASES = [
    ("empty table -> 200 with []",
     lambda: (_client().get("/api/list").status_code,
              _client().get("/api/list").json()),
     (200, [])),

    ("done+spam row: auto vm/shot True, ftc/fcc/tcpa False, paths parsed to list",
     lambda: (lambda it: (it["caller_number"], _b(it["is_spam"]),
                          it["screenshot_paths"], _b(it["vm"]), _b(it["shot"]),
                          _b(it["ftc"]), _b(it["fcc"]), _b(it["tcpa"])))
             (_item(_seed(status="done", caller_number="+15551234567", is_spam=1,
                          screenshot_paths=json.dumps(["/shots/a.png", "/shots/b.png"]),
                          screenshot_ingested=1))),
     ("+15551234567", (True, False, True), ["/shots/a.png", "/shots/b.png"],
      (True, False, True), (True, False, True),
      (False, True, True), (False, True, True), (False, True, True))),

    ("overrides win: ov_vm=1/ov_shot=0/ov_ftc=1/ov_tcpa=1 on a pending row",
     lambda: (lambda it: (_b(it["vm"]), _b(it["shot"]), _b(it["ftc"]),
                          _b(it["fcc"]), _b(it["tcpa"])))
             (_item(_seed(ov_vm=1, ov_shot=0, ov_ftc=1, ov_tcpa=1))),
     ((True, False, True), (False, True, True), (True, False, True),
      (False, True, True), (True, False, True))),

    ("override 0 must beat auto: done+ingested row with ov_vm=0/ov_shot=0",
     lambda: (lambda it: (_b(it["vm"]), _b(it["shot"])))
             (_item(_seed(status="done", screenshot_ingested=1, ov_vm=0, ov_shot=0))),
     ((False, True, True), (False, True, True))),

    ("regression: pre-existing keys unchanged on a plain row",
     lambda: (lambda it: (it["orig_name"], it["status"], it["transcript"] is None,
                          it["duration_secs"],
                          it["audio_url"].startswith("/audio/fix_"),
                          it["caller_last4"] is None, it["progress"] is None,
                          it["callback_number"] is None))
             (_item(_seed())),
     ("shared.wav", "pending", True, 2.5, True, True, True, True)),
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
