"""Adversarial fixture for: vm-status-cells (FTC/FCC/TCPA + schema + delete).

A LEGACY DB (every current column EXCEPT tcpa_filed) is seeded in a temp
DATA_DIR before importing server, so init_db's ALTER migration must add
tcpa_filed. AUTH_TOKEN is left unset so the /mark round-trip is open.
"""
import os
import sys
import sqlite3
import tempfile
import importlib.util

DATA = tempfile.mkdtemp()
os.environ["DATA_DIR"] = DATA
os.makedirs(os.path.join(DATA, "audio"), exist_ok=True)

# Legacy schema: the full current column set MINUS tcpa_filed.
_db = os.path.join(DATA, "voicemails.db")
_con = sqlite3.connect(_db)
_con.execute(
    "CREATE TABLE voicemails ("
    "id TEXT PRIMARY KEY, created_at REAL, orig_name TEXT, audio_path TEXT,"
    "status TEXT, transcript TEXT, duration_secs REAL, caller_number TEXT,"
    "is_spam INTEGER, is_robocall INTEGER, call_category TEXT,"
    "caller_company TEXT, callback_number TEXT, caller_url TEXT,"
    "what_said_summary TEXT, identifiability TEXT, tcpa_provisions TEXT,"
    "caller_last4 TEXT, progress INTEGER, has_screenshots INTEGER,"
    "ftc_filed INTEGER DEFAULT 0, fcc_filed INTEGER DEFAULT 0)")
_con.execute("INSERT INTO voicemails (id, created_at, status) "
             "VALUES ('vm1', 1700000000.0, 'done')")
_con.commit(); _con.close()

spec = importlib.util.spec_from_file_location("target", 'server.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)   # init_db() runs here -> ALTER adds tcpa_filed

from fastapi.testclient import TestClient
client = TestClient(target.app)

CROSS = "✗"   # red, not filed
CHECK = "✓"   # green, filed


def cols():
    c = target._db()
    try:
        return {r[1] for r in c.execute("PRAGMA table_info(voicemails)")}
    finally:
        c.close()


def flag_of(vm, name):
    for row in target.api_list():
        if row["id"] == vm:
            return row.get(name)
    return "MISSING_ROW"


def mark(set_flag, flag="ftc_filed"):
    return target._mark_cell(flag, "abc123", set_flag)


def tcpa(set_flag):
    return target._tcpa_cell("abc123", set_flag)


def render(tcpa_filed=0, ftc=0, fcc=0):
    return target._render_index([
        {"id": "rr", "created_at": 0, "status": "new", "transcript": None,
         "caller_number": None, "callback_number": None, "audio_path": None,
         "has_screenshots": 0, "ftc_filed": ftc, "fcc_filed": fcc,
         "tcpa_filed": tcpa_filed}])


CASES = [
    # --- schema migration: ALTER added tcpa_filed to the legacy DB ---
    ("ALTER migration added tcpa_filed to the existing DB",
     lambda: "tcpa_filed" in cols(), True),
    ("api_list exposes tcpa_filed for the legacy row (default 0)",
     lambda: flag_of("vm1", "tcpa_filed"), 0),

    # --- tcpa_filed is whitelisted + round-trips through /mark + api_list ---
    ("tcpa_filed is in the /mark whitelist",
     lambda: "tcpa_filed" in target._MARK_FLAGS, True),
    ("POST /mark flag=tcpa_filed value=1 -> 200",
     lambda: client.post("/complaint/vm1/mark",
                         data={"flag": "tcpa_filed", "value": "1"}).status_code, 200),
    ("after mark=1, api_list reports tcpa_filed == 1",
     lambda: flag_of("vm1", "tcpa_filed"), 1),
    ("POST /mark flag=tcpa_filed value=0 -> unmark round-trips to 0",
     lambda: (client.post("/complaint/vm1/mark",
                          data={"flag": "tcpa_filed", "value": "0"}).status_code == 200)
             and (flag_of("vm1", "tcpa_filed") == 0), True),

    # --- _mark_cell (FTC/FCC): red cross->report when unfiled, green check when filed ---
    ("mark not-done shows red cross linking to report, styled red",
     lambda: (CROSS in mark(0)) and ("/complaint/abc123/report" in mark(0))
             and ("color:#c00" in mark(0)), True),
    ("mark not-done must NOT show the green check",
     lambda: CHECK in mark(0), False),
    ("mark done shows green check, styled green",
     lambda: (CHECK in mark(1, "fcc_filed")) and ("color:#080" in mark(1, "fcc_filed")), True),
    ("mark done must NOT show the red cross",
     lambda: CROSS in mark(1, "fcc_filed"), False),
    ("mark keeps a /mark toggle in both states",
     lambda: ("/complaint/abc123/mark" in mark(0)) and ("/complaint/abc123/mark" in mark(1)), True),

    # --- _tcpa_cell: pure manual toggle, NO report flow ---
    ("tcpa not-filed shows red cross, styled red",
     lambda: (CROSS in tcpa(0)) and ("color:#c00" in tcpa(0)), True),
    ("tcpa not-filed must NOT show the green check",
     lambda: CHECK in tcpa(0), False),
    ("tcpa not-filed posts to /mark (manual toggle, not a report link)",
     lambda: "/complaint/abc123/mark" in tcpa(0), True),
    ("tcpa not-filed does NOT link to the report flow",
     lambda: "/complaint/abc123/report" in tcpa(0), False),
    ("tcpa not-filed toggle value is 1 (click to mark filed)",
     lambda: 'name="value" value="1"' in tcpa(0), True),
    ("tcpa carries the tcpa_filed flag name",
     lambda: 'name="flag" value="tcpa_filed"' in tcpa(0), True),
    ("tcpa filed shows green check, styled green, NO cross",
     lambda: (CHECK in tcpa(1)) and ("color:#080" in tcpa(1)) and (CROSS not in tcpa(1)), True),
    ("tcpa filed toggle value is 0 (click to unmark)",
     lambda: 'name="value" value="0"' in tcpa(1), True),

    # --- _delete_cell: Delete affordance survives ---
    ("delete cell posts to /delete/{id}",
     lambda: "/delete/xyz" in target._delete_cell("xyz"), True),

    # --- _render_index: header shows TCPA, Actions is gone ---
    ("header includes a TCPA column",
     lambda: "<th>TCPA</th>" in render(), True),
    ("header no longer includes the Actions column",
     lambda: "<th>Actions</th>" in render(), False),
    ("a rendered row still carries a Delete control",
     lambda: "/delete/rr" in render(), True),
    ("render: tcpa_filed=0 row shows a red cross (via the TCPA cell)",
     lambda: CROSS in render(tcpa_filed=0), True),
    ("render: tcpa_filed=1 row shows a green check",
     lambda: CHECK in render(tcpa_filed=1), True),
]


def main():
    if len(CASES) < 3:
        print("  SCAFFOLD_INCOMPLETE"); return 1
    fails = 0
    for desc, thunk, want in CASES:
        try:
            got = thunk()
        except Exception as e:
            print("  FAIL {} -- raised {}: {}".format(desc, type(e).__name__, e)); fails += 1; continue
        if got != want:
            print("  FAIL {} -- got {!r}, want {!r}".format(desc, got, want)); fails += 1
    print("  {}/{} case(s) passed".format(len(CASES) - fails, len(CASES)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
