#!/usr/bin/env python3
"""Reference impl: insert the /set-caller route into server.py.

Inserts before the existing `@app.get("/audio/{vm_id}")` route. Proves the task
is satisfiable and the verify enforces the spec. The gate reverts it after.
"""
import pathlib
import sys

wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = wt / "server.py"
t = p.read_text()

ANCHOR = '@app.get("/audio/{vm_id}")'

ROUTE = '''@app.post("/set-caller")
def set_caller(caller_number: str = Form(default=None), caller_last4: str = Form(default=None)):
    # Access-gated upstream (Cloudflare) -- no bearer required.
    num = (caller_number or "").strip()
    if not num:
        raise HTTPException(status_code=400, detail="missing caller_number")
    source = caller_last4 if caller_last4 and sum(c.isdigit() for c in caller_last4) >= 4 else num
    last4 = "".join(ch for ch in source if ch.isdigit())[-4:]
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, caller_number FROM voicemails WHERE caller_last4 = ?"
            " ORDER BY (caller_number IS NULL) DESC, created_at DESC LIMIT 1",
            (last4,)).fetchone()
        matched = "last4"
        if row is None:
            row = conn.execute(
                "SELECT id, caller_number FROM voicemails"
                " ORDER BY created_at DESC LIMIT 1").fetchone()
            matched = "recent"
        if row is None:
            raise HTTPException(status_code=404, detail="no voicemails")
        conn.execute(
            "UPDATE voicemails SET caller_number = ?,"
            " caller_last4 = COALESCE(caller_last4, ?) WHERE id = ?",
            (num, last4, row["id"]))
        conn.commit()
        return {"ok": True, "id": row["id"], "matched": matched}
    finally:
        conn.close()


'''

assert ANCHOR in t, "refimpl anchor not found -- did the target change?"
p.write_text(t.replace(ANCHOR, ROUTE + ANCHOR, 1))
print("refimpl applied")
