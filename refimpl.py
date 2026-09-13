#!/usr/bin/env python3
"""Reference impl for: voicemail-ui-s3-toggle

The gate applies this, runs the verify, and reverts it. It proves two things at
once: the task is SATISFIABLE as specified, and the verify actually ENFORCES
the spec (a refimpl that goes green while a "Must contain" literal is absent
means the verify is benign).

Appends the POST /checkmark/{vm_id}/{field} route to server.py. The file ends
with a plain route definition (no `if __name__` guard), so appending module-
level code is safe and needs no anchor.
"""
import pathlib
import sys

wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = wt / 'server.py'
t = p.read_text()

ROUTE = '''
CHECKMARK_FIELDS = ("vm", "shot", "ftc", "fcc", "tcpa")


def _checkmark_auto(row, field):
    """Auto (non-overridden) value for a checkmark field on one row."""
    if field == "vm":
        return row["status"] == "done"
    if field == "shot":
        return bool(row["screenshot_ingested"])
    return False


@app.post("/checkmark/{vm_id}/{field}")
def toggle_checkmark(
    vm_id: str,
    field: str,
    authorization: str = Header(default=None),
):
    _check_auth(authorization)
    if field not in CHECKMARK_FIELDS:
        raise HTTPException(status_code=400, detail="invalid field")

    conn = _db()
    try:
        row = conn.execute(
            "SELECT status, screenshot_ingested, ov_vm, ov_shot,"
            " ov_ftc, ov_fcc, ov_tcpa FROM voicemails WHERE id = ?",
            (vm_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown voicemail")
        current = _checkmark_auto(row, field) if row["ov_" + field] is None else bool(row["ov_" + field])
        new_val = 1 if not current else 0
        conn.execute(
            "UPDATE voicemails SET ov_{} = ? WHERE id = ?".format(field),
            (new_val, vm_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"field": field, "value": bool(new_val)}
'''

if '@app.post("/checkmark/{vm_id}/{field}")' in t:
    print("refimpl already applied")
else:
    if not t.endswith("\n"):
        t += "\n"
    p.write_text(t + ROUTE)
    print("refimpl applied")
