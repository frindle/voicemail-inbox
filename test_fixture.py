"""Adversarial fixture for: voicemail-ui-s1-schema

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
import os
import sqlite3
import sys
import tempfile
import importlib.util

# Point the app at a throwaway DATA_DIR BEFORE server.py is imported -- it
# creates its audio dir and runs init_db() at import time.
_TMP = tempfile.mkdtemp(prefix="vmfix_")
os.environ["DATA_DIR"] = os.path.join(_TMP, "data")

spec = importlib.util.spec_from_file_location("target", 'server.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


# (type, dflt_value) exactly as PRAGMA table_info reports them.
NEW_COLS = {
    "screenshot_ingested": ("INTEGER", "0"),
    "screenshot_paths": ("TEXT", None),
    "ov_vm": ("INTEGER", None),
    "ov_shot": ("INTEGER", None),
    "ov_ftc": ("INTEGER", None),
    "ov_fcc": ("INTEGER", None),
    "ov_tcpa": ("INTEGER", None),
}


def _info(dbpath):
    conn = sqlite3.connect(dbpath)
    try:
        return {r[1]: (r[2], r[4]) for r in
                conn.execute("PRAGMA table_info(voicemails)")}
    finally:
        conn.close()


def _new_cols_ok(dbpath):
    info = _info(dbpath)
    return all(info.get(c) == v for c, v in NEW_COLS.items())


def _row_count():
    conn = sqlite3.connect(target.DB_PATH)
    try:
        return conn.execute("SELECT COUNT(*) FROM voicemails").fetchone()[0]
    finally:
        conn.close()


def _set_db(dbp):
    target.DB_PATH = dbp
    return True


def _legacy_db():
    """A pre-screenshot v1 DB with one row -- the in-place migration path."""
    dbp = os.path.join(_TMP, "legacy.db")
    conn = sqlite3.connect(dbp)
    conn.execute(
        """CREATE TABLE voicemails (
            id TEXT PRIMARY KEY, created_at REAL, orig_name TEXT,
            audio_path TEXT, status TEXT, transcript TEXT,
            duration_secs REAL)""")
    conn.execute(
        "INSERT INTO voicemails VALUES ('legacy-1', 1.0, 'a.wav',"
        " '/x/a.wav', 'done', 'hello', 3.5)")
    conn.commit()
    conn.close()
    return dbp


def _idempotent():
    target.init_db()
    target.init_db()
    return _new_cols_ok(target.DB_PATH)


def _legacy_migrate():
    _set_db(_legacy_db())
    target.init_db()
    return _new_cols_ok(target.DB_PATH) and _row_count() == 1


def _defaults_check():
    """Insert a row that omits every new column; read the defaults back."""
    conn = sqlite3.connect(target.DB_PATH)
    try:
        conn.execute(
            "INSERT INTO voicemails (id, created_at, orig_name, audio_path,"
            " status, transcript, duration_secs)"
            " VALUES ('fix-1', 2.0, 'b.wav', '/x/b.wav', 'done', 'hi', 1.0)")
        conn.commit()
        row = conn.execute(
            "SELECT screenshot_ingested, ov_vm FROM voicemails"
            " WHERE id='fix-1'").fetchone()
        return tuple(row)
    finally:
        conn.close()


CASES = [
    ("fresh DB: all seven new columns with exact type/default",
     lambda: _new_cols_ok(target.DB_PATH), True),

    # A plausible wrong fix (columns only in CREATE TABLE, or an unguarded
    # ALTER) breaks here: init_db must stay safe to re-run.
    ("idempotent re-run of init_db() keeps the schema intact",
     _idempotent, True),

    # Catches "added to CREATE TABLE but not the migration loop": a legacy v1
    # DB must gain the columns in place and keep its row.
    ("legacy v1 DB migrates in place and keeps its row",
     _legacy_migrate, True),

    # Catches a missing DEFAULT on screenshot_ingested or a NOT NULL/default
    # on the nullable ov_* override flags.
    ("screenshot_ingested defaults to 0; ov_vm stays NULL when unset",
     lambda: _defaults_check(), (0, None)),

    # Regression half: original v1 columns and is_spam default must survive.
    ("regression: v1 columns intact, is_spam still INTEGER DEFAULT 0",
     lambda: all(c in _info(target.DB_PATH) for c in
                 ("id", "created_at", "orig_name", "audio_path", "status",
                  "transcript", "duration_secs")) and
             _info(target.DB_PATH).get("is_spam") == ("INTEGER", "0"), True),
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
