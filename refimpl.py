#!/usr/bin/env python3
"""Reference impl for: ingest-screenshots.

Appends the endpoint (+ parser + matcher) to server.py. The gate applies this,
runs verify, then reverts it — proving the task is satisfiable and the verify
enforces the spec. Doubles as the review reference for the model's diff.
"""
import pathlib
import sys

wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = wt / 'server.py'
t = p.read_text()

MARKER = "# --- ingest-screenshots (reference impl) ---"
if MARKER in t:
    print("refimpl already applied")
    sys.exit(0)

BLOCK = '''

# --- ingest-screenshots (reference impl) ---
import re as _ss_re


def parse_screenshot_ocr(text):
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    TIME = _ss_re.compile(r"\\b(\\d{1,2}):(\\d{2})\\b")

    def digits_of(s):
        d = _ss_re.sub(r"\\D", "", s)
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        return d

    def is_marker(ln):
        low = ln.lower()
        return (low.startswith("today") or low.startswith("yesterday")
                or bool(_ss_re.match(r"(mon|tue|wed|thu|fri|sat|sun)", low))
                or bool(_ss_re.match(r"\\d{1,2}/\\d{1,2}", low)))

    phone_idx = [i for i, ln in enumerate(lines) if len(digits_of(ln)) >= 10]
    raw = []
    for k, i in enumerate(phone_idx):
        d = digits_of(lines[i])[-10:]
        j = phone_idx[k + 1] if k + 1 < len(phone_idx) else len(lines)
        block = lines[i + 1:j]
        marker = None
        for bi, bln in enumerate(block):
            if is_marker(bln):
                marker = bi
                break
        pre = block[:marker] if marker is not None else block
        dur = None
        for bln in pre:
            m = TIME.search(bln)
            if m:
                dur = int(m.group(1)) * 60 + int(m.group(2))
                break
        raw.append({"digits": d, "last4": d[-4:], "number": "+1" + d, "duration": dur})

    seen, ordered = {}, []
    for e in raw:
        if e["digits"] in seen:
            if seen[e["digits"]]["duration"] is None and e["duration"] is not None:
                seen[e["digits"]]["duration"] = e["duration"]
            continue
        seen[e["digits"]] = e
        ordered.append(e)
    return ordered


def match_entries_to_voicemails(entries):
    matched, unmatched = [], []
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, duration_secs FROM voicemails WHERE caller_number IS NULL"
            " ORDER BY created_at DESC"
        ).fetchall()
        cand = [{"id": r["id"], "duration": r["duration_secs"]} for r in rows]
        claimed = set()
        for e in entries:
            chosen, by = None, None
            if e["duration"] is not None:
                for c in cand:
                    if c["id"] in claimed:
                        continue
                    if c["duration"] is not None and abs(c["duration"] - e["duration"]) <= 2:
                        chosen, by = c, "duration"
                        break
            if chosen is None:
                for c in cand:
                    if c["id"] in claimed:
                        continue
                    chosen, by = c, "order"
                    break
            if chosen is None:
                unmatched.append(e["number"])
                continue
            claimed.add(chosen["id"])
            conn.execute(
                "UPDATE voicemails SET caller_number = ?,"
                " caller_last4 = COALESCE(caller_last4, ?) WHERE id = ?",
                (e["number"], e["last4"], chosen["id"]),
            )
            matched.append({"id": chosen["id"], "number": e["number"],
                            "last4": e["last4"], "by": by})
        conn.commit()
    finally:
        conn.close()
    return matched, unmatched


@app.post("/ingest-screenshots")
def ingest_screenshots(ocr_text: str = Form(default=None)):
    if not (ocr_text or "").strip():
        raise HTTPException(status_code=400, detail="missing ocr_text")
    entries = parse_screenshot_ocr(ocr_text)
    matched, unmatched = match_entries_to_voicemails(entries)
    return {"matched": matched, "unmatched": unmatched}
'''

p.write_text(t + BLOCK)
print("refimpl applied")
