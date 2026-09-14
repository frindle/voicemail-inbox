"""Adversarial fixture for: vm-pdf-export.

AUTH_TOKEN is set BEFORE importing server.py (server reads it at import time),
so the /export/pdf auth gate is exercised for real (401 without, 200 with). A
known voicemail row is inserted so the PDF's *content* can be asserted -- with
pageCompression=0 the drawn text is searchable in the PDF bytes.
"""
import os
import sys
import importlib.util

os.environ["AUTH_TOKEN"] = "sekret-test-token"

spec = importlib.util.spec_from_file_location("target", 'server.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)

# Seed a row with distinctive numbers so we can find them in the PDF.
_c = target._db()
_c.execute(
    "INSERT OR REPLACE INTO voicemails (id, created_at, caller_number,"
    " callback_number, status) VALUES (?,?,?,?,?)",
    ("pdftestrow", 1700000000.0, "3218661469", "5551234567", "done"))
_c.commit(); _c.close()

from fastapi.testclient import TestClient
client = TestClient(target.app)
AUTH = {"Authorization": "Bearer sekret-test-token"}


def r_auth():
    return client.get("/export/pdf", headers=AUTH)


CASES = [
    ("no bearer -> 401 (auth gate present)",
     lambda: client.get("/export/pdf").status_code, 401),
    ("wrong bearer -> 401",
     lambda: client.get("/export/pdf", headers={"Authorization": "Bearer nope"}).status_code, 401),
    ("valid bearer -> 200",
     lambda: r_auth().status_code, 200),
    ("content-type is application/pdf",
     lambda: "application/pdf" in r_auth().headers.get("content-type", ""), True),
    ("body starts with the %PDF magic",
     lambda: r_auth().content[:4] == b"%PDF", True),
    ("body is a non-trivial PDF, not an empty stub",
     lambda: len(r_auth().content) > 500, True),
    ("PDF CONTENT includes the caller_number (it is a PDF *of the call log*)",
     lambda: b"3218661469" in r_auth().content, True),
    ("PDF CONTENT includes the callback_number too (not just From)",
     lambda: b"5551234567" in r_auth().content, True),
    ("PDF CONTENT includes the title",
     lambda: b"Voicemail call log" in r_auth().content, True),
    ("front page links to the export endpoint",
     lambda: "/export/pdf" in client.get("/").text, True),
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
