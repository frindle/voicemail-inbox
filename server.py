"""Voicemail inbox -- single-file FastAPI app.

An iPhone Shortcut POSTs a shared voicemail audio file to /ingest; the app
stores it, records it in SQLite, and later shows every voicemail on a web
page with an HTML5 audio player plus its transcript. Transcription itself
runs elsewhere (a Whisper job) and is written back via /internal/transcript --
this app only STORES, SERVES, and DISPLAYS.
"""
import html
import json
import os
import re
import sqlite3
import time
import urllib.parse
import uuid

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse

AUTH_TOKEN = os.environ.get("AUTH_TOKEN", "")
DATA_DIR = os.environ.get("DATA_DIR", "./data")
AUDIO_DIR = os.path.join(DATA_DIR, "audio")
DB_PATH = os.path.join(DATA_DIR, "voicemails.db")

os.makedirs(AUDIO_DIR, exist_ok=True)

app = FastAPI(title="Voicemail Inbox")


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with _db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS voicemails (
                id TEXT PRIMARY KEY,
                created_at REAL,
                orig_name TEXT,
                audio_path TEXT,
                status TEXT,
                transcript TEXT,
                duration_secs REAL,
                caller_number TEXT,
                is_spam INTEGER DEFAULT 0
            )"""
        )
        # Tolerate a legacy DB that already has rows under the v1 schema:
        # add the new columns in place instead of dropping/recreating.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(voicemails)")}
        if "caller_number" not in cols:
            conn.execute(
                "ALTER TABLE voicemails ADD COLUMN caller_number TEXT")
        if "is_spam" not in cols:
            conn.execute(
                "ALTER TABLE voicemails ADD COLUMN is_spam INTEGER DEFAULT 0")
        # Structured DNC/robocall complaint fields (derived at transcript time).
        for col, decl in (
            ("is_robocall", "INTEGER"),
            ("call_category", "TEXT"),
            ("caller_company", "TEXT"),
            ("callback_number", "TEXT"),
            ("caller_url", "TEXT"),
            ("what_said_summary", "TEXT"),
            ("identifiability", "TEXT"),
            # Reserved for the later TCPA layer -- add now so no migration needed.
            ("tcpa_provisions", "TEXT"),
            ("caller_last4", "TEXT"),
            ("progress", "INTEGER"),
            ("screenshot_ingested", "INTEGER DEFAULT 0"),
            ("screenshot_paths", "TEXT"),
            ("ov_vm", "INTEGER"),
            ("ov_shot", "INTEGER"),
            ("ov_ftc", "INTEGER"),
            ("ov_fcc", "INTEGER"),
            ("ov_tcpa", "INTEGER"),
        ):
            if col not in cols:
                conn.execute(
                    "ALTER TABLE voicemails ADD COLUMN {} {}".format(col, decl))


init_db()


def enqueue_transcription(vm_id: str, audio_path: str):
    """Placeholder queue hook -- real wiring is injected later."""
    return None


def _check_auth(authorization):
    if not AUTH_TOKEN:
        return  # open access: no token configured (LAN-only deployment)
    if authorization != "Bearer " + AUTH_TOKEN:
        raise HTTPException(status_code=401, detail="unauthorized")


@app.post("/ingest")
async def ingest(
    file: UploadFile = File(default=None),
    caller_last4: str = Form(default=None),
    authorization: str = Header(default=None),
):
    _check_auth(authorization)
    if file is None:
        raise HTTPException(status_code=400, detail="missing 'file' field")

    vm_id = uuid.uuid4().hex[:12]
    orig_name = file.filename or ""
    ext = os.path.splitext(orig_name)[1] or ".wav"
    audio_path = os.path.join(AUDIO_DIR, vm_id + ext)

    data = await file.read()
    with open(audio_path, "wb") as f:
        f.write(data)

    conn = _db()
    try:
        conn.execute(
            "INSERT INTO voicemails (id, created_at, orig_name, audio_path,"
            " status, transcript, duration_secs, caller_last4, progress)"
            " VALUES (?, ?, ?, ?, 'processing', NULL, NULL, ?, 0)",
            (vm_id, time.time(), orig_name, audio_path,
             (caller_last4 or "").strip() or None),
        )
        conn.commit()
    finally:
        conn.close()

    enqueue_transcription(vm_id, audio_path)
    return {"id": vm_id, "status": "processing"}


# Prerecorded/robocall markers -- case-insensitive substring match.
ROBOCALL_PATTERNS = (
    "prerecorded",
    "recorded message",
    "this is an automated",
    "automated message",
    "press 1",
    "press one",
    "do not hang up",
    "final notice",
    "this is a courtesy call",
    "robocall",
)

# Category priority order: FIRST matching category wins. Keywords are matched
# on word boundaries (so `ssa` must NOT match inside `message`).
CALL_CATEGORIES = (
    ("debt", ("debt", "credit card", "loan", "lower your interest")),
    ("impersonator", ("irs", "social security", "ssa",
                      "warrant for your arrest", "arrest", "federal",
                      "suspended")),
    ("medical", ("prescription", "medication", "medical")),
    ("home_security", ("home security", "alarm system")),
    ("tech_support", ("tech support", "virus", "microsoft")),
    ("energy", ("solar", "energy", "utility")),
    ("home_improvement", ("roofing", "gutter", "home improvement")),
    ("work_from_home", ("work from home", "make money")),
    ("warranty", ("warranty", "protection plan")),
    ("sweepstakes", ("sweepstakes", "you have won", "prize",
                     "lottery", "gift card")),
    ("vacation", ("vacation", "timeshare", "cruise")),
    ("charity", ("donation", "charity", "donate")),
)


def _normalize_phone(value):
    """Digits only; drop a leading country `1` on an 11-digit number."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    return digits


def extract_complaint_fields(transcript, caller_number, created_at):
    """Deterministically derive the structured DNC/robocall complaint fields
    from a transcript. Never raises on None/empty input; never HTML-escapes or
    otherwise mangles the text (escaping is the render layer's job)."""
    text = transcript if isinstance(transcript, str) else ""
    low = text.lower()

    is_robocall = 1 if any(p in low for p in ROBOCALL_PATTERNS) else 0

    call_category = "unknown" if is_robocall else "other"
    for name, keywords in CALL_CATEGORIES:
        if any(re.search(r"\b{}\b".format(re.escape(kw)), low)
               for kw in keywords):
            call_category = name
            break

    # Company/name spoken after `from` / `with` / `on behalf of` / `this is`:
    # consecutive Capitalized words.
    caller_company = None
    m = re.search(
        r"\b(?:on behalf of|from|with|this is)\s+"
        r"([A-Z][a-zA-Z0-9&'\-]*(?:\s+[A-Z][a-zA-Z0-9&'\-]*)*)", text)
    if m:
        caller_company = m.group(1).strip()

    # 10-digit phone number spoken IN the body, distinct from the CID.
    callback_number = None
    cid = _normalize_phone(caller_number)
    for m in re.finditer(r"(?<!\d)(?:1[-.\s]?)?"
                         r"(\d{3})[-.\s]?(\d{3})[-.\s]?(\d{4})(?!\d)", text):
        num = _normalize_phone(m.group(0))
        if len(num) == 10 and (not cid or num != cid):
            callback_number = num
            break

    # First website/URL in the body, lowercased.
    caller_url = None
    m = re.search(r"(?:https?://|www\.)[^\s<>\"'()]+", low)
    if m:
        caller_url = m.group(0).rstrip(".,;")

    what_said_summary = " ".join(text.split())[:280]

    if callback_number:
        identifiability = "callback"
    elif caller_number:
        identifiability = "cid_only"
    else:
        identifiability = "none"

    return {
        "is_robocall": is_robocall,
        "call_category": call_category,
        "caller_company": caller_company,
        "callback_number": callback_number,
        "caller_url": caller_url,
        "what_said_summary": what_said_summary,
        "identifiability": identifiability,
    }


@app.post("/internal/transcript")
def set_transcript(
    payload: dict,
    authorization: str = Header(default=None),
):
    _check_auth(authorization)
    vm_id = payload.get("id")
    transcript = payload.get("transcript", "")
    duration = payload.get("duration")

    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, caller_number, created_at FROM voicemails"
            " WHERE id = ?", (vm_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown voicemail")
        fields = extract_complaint_fields(
            transcript, row["caller_number"], row["created_at"])
        conn.execute(
            "UPDATE voicemails SET status = 'done', transcript = ?,"
            " duration_secs = ?, is_robocall = ?, call_category = ?,"
            " caller_company = ?, callback_number = ?, caller_url = ?,"
            " what_said_summary = ?, identifiability = ?,"
            " progress = 100 WHERE id = ?",
            (transcript, duration, fields["is_robocall"],
             fields["call_category"], fields["caller_company"],
             fields["callback_number"], fields["caller_url"],
             fields["what_said_summary"], fields["identifiability"], vm_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"ok": True}


@app.post("/internal/progress")
def set_progress(payload: dict, authorization: str = Header(default=None)):
    _check_auth(authorization)
    vm_id = payload.get("id")
    try:
        progress = int(payload.get("progress"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid progress")
    progress = max(0, min(100, progress))
    conn = _db()
    try:
        cur = conn.execute(
            "UPDATE voicemails SET progress = ? WHERE id = ?",
            (progress, vm_id))
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail="unknown voicemail")
    finally:
        conn.close()
    return {"ok": True, "progress": progress}


@app.post("/delete/{vm_id}")
def delete_voicemail(vm_id: str):
    # Access-gated upstream (Cloudflare) -- no bearer required.
    conn = _db()
    try:
        row = conn.execute(
            "SELECT audio_path FROM voicemails WHERE id = ?", (vm_id,)
        ).fetchone()
        if row is not None:
            conn.execute("DELETE FROM voicemails WHERE id = ?", (vm_id,))
            conn.commit()
            ap = row["audio_path"]
            if ap and os.path.exists(ap):
                try:
                    os.remove(ap)
                except OSError:
                    pass
    finally:
        conn.close()
    return RedirectResponse("/", status_code=303)


@app.post("/set-caller")
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
            (last4,),
        ).fetchone()
        if row is not None:
            matched = "last4"
        else:
            row = conn.execute(
                "SELECT id, caller_number FROM voicemails ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            if row is not None:
                matched = "recent"
        if row is None:
            raise HTTPException(status_code=404, detail="no voicemails")

        conn.execute(
            "UPDATE voicemails SET caller_number = ?,"
            " caller_last4 = COALESCE(caller_last4, ?) WHERE id = ?",
            (num, last4, row["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    return {"ok": True, "id": row["id"], "matched": matched}


@app.get("/audio/{vm_id}")
def get_audio(vm_id: str):
    conn = _db()
    try:
        row = conn.execute(
            "SELECT audio_path FROM voicemails WHERE id = ?", (vm_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None or not os.path.exists(row["audio_path"]):
        raise HTTPException(status_code=404, detail="not found")
    return FileResponse(row["audio_path"])


@app.get("/api/list")
def api_list():
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, created_at, orig_name, status, transcript,"
            " duration_secs, caller_last4, progress, callback_number,"
            " caller_number, is_spam, screenshot_paths, screenshot_ingested,"
            " ov_vm, ov_shot, ov_ftc, ov_fcc, ov_tcpa"
            " FROM voicemails ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()

    def _flag(ov, auto):
        return bool(auto) if ov is None else bool(ov)

    items = []
    for r in rows:
        paths = r["screenshot_paths"]
        items.append({
            "id": r["id"],
            "created_at": r["created_at"],
            "orig_name": r["orig_name"],
            "status": r["status"],
            "transcript": r["transcript"],
            "duration_secs": r["duration_secs"],
            "caller_last4": r["caller_last4"],
            "progress": r["progress"],
            "callback_number": r["callback_number"],
            "audio_url": "/audio/" + r["id"],
            "caller_number": r["caller_number"],
            "is_spam": bool(r["is_spam"]),
            "screenshot_paths": json.loads(paths) if paths else [],
            "vm": _flag(r["ov_vm"], r["status"] == "done"),
            "shot": _flag(r["ov_shot"], r["screenshot_ingested"]),
            "ftc": _flag(r["ov_ftc"], False),
            "fcc": _flag(r["ov_fcc"], False),
            "tcpa": _flag(r["ov_tcpa"], False),
        })
    return items


FTC_URL = "https://donotcall.gov/report.html"
FCC_URL = "https://consumercomplaints.fcc.gov/"


def _get_row(vm_id: str):
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, created_at, caller_number, transcript,"
            " is_robocall, call_category, caller_company, callback_number,"
            " caller_url, what_said_summary, identifiability"
            " FROM voicemails WHERE id = ?", (vm_id,)
        ).fetchone()
    finally:
        conn.close()
    return row


def _complaint_text(caller_number, created_at, transcript):
    who = caller_number if caller_number else "an unknown number"
    _d, _t12, _ = _dmy_hm(created_at)
    when = "{} at {}".format(_d, _t12) if _d else str(created_at)
    return (
        "I received an unwanted robocall from {} on {}. "
        "The call said: {}".format(who, when, transcript or "")
    )


@app.post("/mark-spam")
def mark_spam(payload: dict, authorization: str = Header(default=None)):
    _check_auth(authorization)
    vm_id = payload.get("id")
    caller_number = (payload.get("caller_number") or "").strip() or None

    conn = _db()
    try:
        row = conn.execute(
            "SELECT id FROM voicemails WHERE id = ?", (vm_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown voicemail")
        if caller_number:
            conn.execute(
                "UPDATE voicemails SET is_spam = 1, caller_number = ?"
                " WHERE id = ?", (caller_number, vm_id),
            )
        else:
            # Re-marking without a caller_number must not wipe the stored one.
            conn.execute(
                "UPDATE voicemails SET is_spam = 1 WHERE id = ?", (vm_id,)
            )
        conn.commit()
    finally:
        conn.close()
    return {"id": vm_id, "is_spam": 1}


CHECKMARK_FIELDS = ("vm", "shot", "ftc", "fcc", "tcpa")


@app.post("/checkmark/{vm_id}/{field}")
def toggle_checkmark(
    vm_id: str, field: str, authorization: str = Header(default=None),
):
    _check_auth(authorization)
    if field not in CHECKMARK_FIELDS:
        raise HTTPException(status_code=400, detail="invalid field")

    conn = _db()
    try:
        row = conn.execute(
            "SELECT status, screenshot_ingested, ov_{} FROM voicemails"
            " WHERE id = ?".format(field), (vm_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown voicemail")
        auto = ((row["status"] == "done") if field == "vm"
                else bool(row["screenshot_ingested"]) if field == "shot"
                else False)
        ov = row["ov_" + field]
        current = bool(auto) if ov is None else bool(ov)
        new_val = 0 if current else 1
        conn.execute(
            "UPDATE voicemails SET ov_{} = ? WHERE id = ?".format(field),
            (new_val, vm_id),
        )
        conn.commit()
    finally:
        conn.close()
    return {"field": field, "value": bool(new_val)}


@app.get("/api/complaint/{vm_id}")
def complaint_json(vm_id: str, authorization: str = Header(default=None)):
    _check_auth(authorization)
    row = _get_row(vm_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown voicemail")
    return {
        "id": row["id"],
        "caller_number": row["caller_number"],
        "call_datetime": row["created_at"],
        "transcript": row["transcript"],
        "complaint_text": _complaint_text(
            row["caller_number"], row["created_at"], row["transcript"]
        ),
        # Structured DNC/robocall extraction (derived at transcript time).
        "is_robocall": row["is_robocall"],
        "call_category": row["call_category"],
        "caller_company": row["caller_company"],
        "callback_number": row["callback_number"],
        "caller_url": row["caller_url"],
        "what_said_summary": row["what_said_summary"],
        "identifiability": row["identifiability"],
        "ftc": FTC_URL,
        "fcc": FCC_URL,
    }


@app.get("/api/report")
def api_report(authorization: str = Header(default=None)):
    _check_auth(authorization)
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT id, caller_number, created_at, transcript FROM voicemails"
            " WHERE is_spam = 1 ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r["id"],
            "caller_number": r["caller_number"],
            "created_at": r["created_at"],
            "transcript": r["transcript"],
        }
        for r in rows
    ]


@app.get("/complaint/{vm_id}", response_class=HTMLResponse)
def complaint_page(vm_id: str):
    row = _get_row(vm_id)
    if row is None:
        raise HTTPException(status_code=404, detail="unknown voicemail")
    caller = (html.escape(row["caller_number"])
              if row["caller_number"] else "(unknown)")
    caller_val = html.escape(row["caller_number"] or "", quote=True)
    callback_val = html.escape(row["callback_number"] or "", quote=True)
    _d, _t12, _ = _dmy_hm(row["created_at"])
    when = "{} at {}".format(_d, _t12) if _d else str(row["created_at"])
    text = html.escape(_complaint_text(
        row["caller_number"], row["created_at"], row["transcript"]))
    vm_esc = html.escape(vm_id, quote=True)
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Report this call</title></head><body>",
        "<h1>Report this robocall</h1>",
        "<p>Caller number: <strong>{}</strong></p>".format(caller),
        "<p>Call time: {}</p>".format(html.escape(when)),
        '<form method="post" action="/complaint/{}/update">'.format(vm_esc),
        '<p><label>Caller number (caller ID):<br>'
        '<input type="text" name="caller_number" value="{}"></label></p>'
        .format(caller_val),
        '<p><label>Callback number (for reverse search):<br>'
        '<input type="text" name="callback_number" value="{}"></label></p>'
        .format(callback_val),
        '<p><button type="submit">Save numbers</button></p>',
        "</form>",
        "<p>Transcript:</p><blockquote>{}</blockquote>".format(
            html.escape(row["transcript"] or "")),
        "<h2>Copy-ready complaint text</h2>",
        '<pre style="white-space:pre-wrap">{}</pre>'.format(text),
        '<p><a href="/complaint/{}/report">'
        "<strong>Auto-fill FTC/FCC complaint &rarr;</strong></a></p>"
        .format(vm_esc),
        '<div style="background:#eef;border:1px solid #99c;'
        'padding:.75rem;margin:1rem 0">'
        "<strong>TCPA:</strong> unwanted robocalls may carry statutory "
        "damages of $500 per call, up to $1,500 per call if willful."
        "</div>",
        "<ul>",
        '<li><a href="{}">File with the FTC (Do Not Call registry)</a>'
        "</li>".format(FTC_URL),
        '<li><a href="{}">File with the FCC</a></li>'.format(FCC_URL),
        "</ul>",
        '</body></html>',
    ]
    return HTMLResponse("".join(parts))


@app.post("/complaint/{vm_id}/update")
def complaint_update(
    vm_id: str,
    caller_number: str = Form(default=None),
    callback_number: str = Form(default=None),
):
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id FROM voicemails WHERE id = ?", (vm_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="unknown voicemail")
        conn.execute(
            "UPDATE voicemails SET caller_number = ?, callback_number = ?"
            " WHERE id = ?",
            ((caller_number or "").strip() or None,
             (callback_number or "").strip() or None, vm_id))
        conn.commit()
    finally:
        conn.close()
    return RedirectResponse("/complaint/" + vm_id, status_code=303)


def _render_index(items):
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Voicemails</title>",
        "<style>"
        "body{font-family:system-ui,sans-serif;max-width:640px;"
        "margin:2rem auto;padding:0 1rem;color:#222}"
        ".item{border-bottom:1px solid #ddd;padding:1rem 0}"
        ".status{color:#888;font-style:italic}"
        "</style></head><body>",
        "<h1>Voicemails</h1>",
    ]
    for it in items:
        parts.append('<div class="item">')
        parts.append(
            '<audio controls src="/audio/%s"></audio>' % html.escape(it["id"])
        )
        if it["status"] != "done":
            prog = it.get("progress")
            if prog is not None:
                parts.append(
                    '<p class="status">Transcribing %d%%</p>' % int(prog))
            else:
                parts.append('<p class="status">Transcribing&hellip;</p>')
        elif it["transcript"]:
            parts.append("<p>%s</p>" % html.escape(it["transcript"]))
        else:
            parts.append("<p></p>")
        if it.get("duration_secs") is not None:
            parts.append(
                '<small>%.1fs</small>' % float(it["duration_secs"])
            )
        parts.append(
            '<p><a href="/complaint/%s">Report spam</a></p>'
            % html.escape(it["id"])
        )
        parts.append(
            '<form method="post" action="/delete/%s" '
            'onsubmit="return confirm(&#39;Delete this voicemail?&#39;);" '
            'style="display:inline">'
            '<button type="submit">Delete</button></form>'
            % html.escape(it["id"], quote=True)
        )
        parts.append("</div>")
    parts.append(
        "<script>"
        "async function refresh(){"
        "try{const r=await fetch('/api/list');"
        "if(r.ok){location.reload();}}"
        "}setInterval(refresh,5000);"
        "</script>"
        "</body></html>"
    )
    return "".join(parts)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def index():
    items = api_list()
    return HTMLResponse(_render_index(items))


# --- agency form field mapping (SEPARATE from the evidence record) ----------
# Field names/ids verified against the LIVE forms (2026-09-11):
#   FTC reportfraud.ftc.gov  -> Angular formcontrolnames on /form/main
#   FCC consumercomplaints.fcc.gov -> Zendesk Phone form ticket_form_id=39744
import datetime as _dt
import urllib.parse as _url

# The Phone-form prefill URL always carries ticket_form_id=39744 (Zendesk).
FCC_PHONE_FORM_ID = "39744"
FCC_NEW_REQUEST = "https://consumercomplaints.fcc.gov/hc/en-us/requests/new"

# call_category -> the exact FTC "What was the call about?" option TEXT
_FTC_ABOUT = {
    "debt": "Reducing your debt (credit cards, mortgage, student loans)",
    "impersonator": "Calls pretending to be government, businesses, or family and friends",
    "medical": "Medical & prescriptions",
    "home_security": "Home security & alarms",
    "tech_support": "Computer & technical support",
    "energy": "Energy, solar, & utilities",
    "home_improvement": "Home improvement & cleaning",
    "work_from_home": "Work from home & other ways to make money",
    "warranty": "Warranties & protection plans",
    "sweepstakes": "Lotteries, prizes & sweepstakes",
    "vacation": "Vacation & timeshares",
    "charity": "Charities",
    "unknown": "Unknown",
}


def _no_angle(s):
    """FCC/Zendesk tf_ prefill forbids < and > in values; strip them."""
    return (s or "").replace("<", "").replace(">", "")


def _dmy_hm(created_at):
    try:
        d = _dt.datetime.fromtimestamp(float(created_at))
    except (TypeError, ValueError):
        return "", "", ""
    return d.strftime("%m/%d/%Y"), d.strftime("%I:%M %p"), d.strftime("%H:%M")


def _best_identifier(ev):
    """The handle a TCPA/DNC claim keys on: the in-body callback beats a
    possibly-spoofed origin CID."""
    return ev.get("callback_number") or ev.get("caller_number") or "unknown number"


def build_ftc_fields(ev):
    """Map evidence -> FTC reportfraud.ftc.gov Angular form (fill-only)."""
    date, _t12, _t24 = _dmy_hm(ev.get("call_datetime"))
    return {
        "_url": "https://reportfraud.ftc.gov/assistant",
        "_category_radio": "Just an annoying call",
        "yesOrNoRobo": "yes" if ev.get("is_robocall") else "no",
        "roboPhone": "",
        "about": _FTC_ABOUT.get(ev.get("call_category"), "Other"),
        "roboDate": date,
        "roboHour": _t12,
        "name": ev.get("caller_company") or "",
        "roboCallerId": ev.get("caller_number") or "",
        "comments": ev.get("what_said_summary") or "",
    }


def build_fcc_fields(ev):
    """Map evidence -> FCC Zendesk Phone form (ticket_form_id=39744). Includes a
    tf_ prefill URL (fill-only; user reviews + submits past the CAPTCHA)."""
    date, time12, _t24 = _dmy_hm(ev.get("call_datetime"))
    subject = _no_angle(
        "Unwanted robocall from {}".format(_best_identifier(ev)))
    extra = []
    if ev.get("callback_number"):
        extra.append("Call-back number given in message: "
                     + ev["callback_number"])
    if ev.get("caller_company"):
        extra.append("Company/name stated: " + ev["caller_company"])
    if ev.get("caller_url"):
        extra.append("Website mentioned: " + ev["caller_url"])
    extra.append("Identifiability: " + (ev.get("identifiability") or "none"))
    description = _no_angle(ev.get("what_said_summary") or "")
    additional = _no_angle(" | ".join(extra))
    custom = {
        "22619354": "telemarketing_phone",
        "360000167206": "phone_unwanted_calls_all_other_unwanted_calls",
        "22787840": ("prerecorded_voice_type_of_call_telemarketing"
                     if ev.get("is_robocall")
                     else "live_voice_type_of_call_telemarketing"),
        "22664804": _no_angle(ev.get("caller_number") or ""),
        "22591154": date,
        "22732340": time12,
        "22664784": additional,
        "22625554": "yes_telemarketing_services",
    }
    params = [("ticket_form_id", FCC_PHONE_FORM_ID),
              ("tf_subject", subject),
              ("tf_description", description)]
    for cid, val in custom.items():
        if val:
            params.append(("tf_" + cid, val))
    prefill_url = FCC_NEW_REQUEST + "?" + _url.urlencode(params)
    return {
        "ticket_form_id": FCC_PHONE_FORM_ID,
        "subject": subject,
        "description": description,
        "email": "",
        "custom_fields": custom,
        "prefill_url": prefill_url,
    }


def build_autofill(row):
    """Assemble the agency-agnostic evidence record + both agency field maps.
    Evidence is kept SEPARATE from the FTC/FCC maps so a future TCPA
    demand-letter/packet exporter can consume the same evidence."""
    ev = {
        "id": row["id"],
        "caller_number": row["caller_number"],
        "call_datetime": row["created_at"],
        "is_robocall": row["is_robocall"],
        "call_category": row["call_category"],
        "caller_company": row["caller_company"],
        "callback_number": row["callback_number"],
        "caller_url": row["caller_url"],
        "what_said_summary": row["what_said_summary"],
        "identifiability": row["identifiability"],
        "tcpa_provisions": row["tcpa_provisions"],
        "transcript": row["transcript"],
    }
    return {
        "evidence": ev,
        "ftc": build_ftc_fields(ev),
        "fcc": build_fcc_fields(ev),
    }


@app.get("/api/complaint/{vm_id}/autofill")
def complaint_autofill(vm_id: str, authorization: str = Header(default=None)):
    _check_auth(authorization)
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, created_at, caller_number, transcript, is_robocall,"
            " call_category, caller_company, callback_number, caller_url,"
            " what_said_summary, identifiability, tcpa_provisions"
            " FROM voicemails WHERE id = ?", (vm_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown voicemail")
    return build_autofill(row)


# --- fill-only bookmarklet generator ----------------------------------------
# The live FTC form (reportfraud.ftc.gov) is an Angular SPA with NO URL-prefill
# and index-encoded <select> option values ("9: 12"); the FCC form is Zendesk.
# So the uniform fill mechanism is a per-complaint BOOKMARKLET run while on the
# live form (plus the FCC tf_ prefill link as a zero-JS shortcut). The script:
#   * sets each value with the NATIVE value setter
#     (Object.getOwnPropertyDescriptor(...,'value').set) and then dispatches
#     both an 'input' and a 'change' event, so Angular/React reactive forms
#     register the change (a plain `.value=` is silently ignored);
#   * moves <select>s by matching OPTION TEXT and assigning selectedIndex --
#     writing the encoded option .value does NOT move the Angular selection;
#   * reaches the id-less "Describe what happened" textarea via its
#     formcontrolname with document.querySelector (getElementById returns null
#     because there is no such id);
#   * FILL_ONLY_NEVER_SUBMIT: it fills and STOPS. It never calls submit,
#     requestSubmit, or clicks a commit control -- the user reviews, clears
#     the CAPTCHA, and submits.

_FTC_DOM_MAP = {
    "yesOrNoRobo": {"radio": "yesOrNoRobo"},
    "roboCallerId": {"id": "roborcroboCallerId"},
    "roboPhone": {"id": "robordrobophone"},
    "roboDate": {"id": "robordroboDate"},
    "name": {"id": "roborcname"},
    "comments": {"textarea": "comments"},
    "about": {"select": "robordabout"},
    "roboHour": {"select": "robordroboHour"},
}

_FCC_DOM_MAP = {
    "subject": {"id": "request_subject"},
    "description": {"textarea_id": "request_description"},
    "email": {"id": "request_anonymous_requester_email"},
}

_FILL_ENGINE_JS = (
    "var FILL_ONLY_NEVER_SUBMIT=true;"
    "function setVal(el,v){"
    "if(!el)return;"
    "var d=Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el),'value');"
    "d.set.call(el,String(v));"
    "el.dispatchEvent(new Event('input',{bubbles:true}));"
    "el.dispatchEvent(new Event('change',{bubbles:true}));}"
    "function selByText(el,text){"
    "if(!el)return;"
    "for(var i=0;i<el.options.length;i++){"
    "var o=el.options[i];"
    "if((o.text||o.textContent)===text){"
    "el.selectedIndex=i;"
    "el.dispatchEvent(new Event('change',{bubbles:true}));"
    "return;}}}"
    "function setRadio(name,val){"
    "var rs=document.getElementsByName(name);"
    "for(var i=0;i<rs.length;i++){"
    "if(rs[i].value===val){rs[i].click();return;}}}"
    "for(var k in D){"
    "var v=D[k];"
    "if(v===''||v===null||v===undefined)continue;"
    "var m=MAP[k]||{};"
    "if(m.id){setVal(document.getElementById(m.id),v);}"
    "else if(m.textarea_id){"
    "setVal(document.getElementById(m.textarea_id),v);}"
    "else if(m.textarea){"
    "setVal(document.querySelector('[formcontrolname=\"'+m.textarea+'\"]'),v);}"
    "else if(m.select){selByText(document.getElementById(m.select),String(v));}"
    "else if(m.radio){setRadio(m.radio,String(v));}}"
    "for(var c in CF){"
    "var ce=document.getElementById('request_custom_fields_'+c);"
    "if(ce)setVal(ce,CF[c]);}"
)


def build_fill_script(agency, fieldmap):
    """Build a fill-only `javascript:` bookmarklet for one agency's live form.

    The fieldmap values travel with the bookmarklet as embedded JSON (D), and a
    logical-field -> live-DOM-id map (MAP) tells it which stable id / select /
    radio group / formcontrolname to hit; FCC custom fields ride along in CF,
    addressed as request_custom_fields_<id>. FILL_ONLY_NEVER_SUBMIT: the script
    fills and stops -- no submit(), no requestSubmit(), no commit click."""
    agency = (agency or "").lower()
    if agency == "ftc":
        dom_map = _FTC_DOM_MAP
        custom = {}
    else:
        dom_map = _FCC_DOM_MAP
        custom = dict((fieldmap or {}).get("custom_fields") or {})
    body = (
        "var D=" + json.dumps(fieldmap) + ";"
        "var MAP=" + json.dumps(dom_map) + ";"
        "var CF=" + json.dumps(custom) + ";"
        + _FILL_ENGINE_JS
    )
    return "javascript:" + body


@app.get("/complaint/{vm_id}/report", response_class=HTMLResponse)
def complaint_report_page(vm_id: str):
    """Public fill-only report page for one voicemail (like /complaint/<id>).

    Offers the FCC tf_ prefill link (zero-JS shortcut), FTC + FCC bookmarklets,
    and an explicit no-auto-submit notice. NOTHING IS SUBMITTED by any of it."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, created_at, caller_number, transcript, is_robocall,"
            " call_category, caller_company, callback_number, caller_url,"
            " what_said_summary, identifiability, tcpa_provisions"
            " FROM voicemails WHERE id = ?", (vm_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail="unknown voicemail")

    af = build_autofill(row)
    fcc_map = af["fcc"]
    best_id = html.escape(_best_identifier(af["evidence"]))
    caller = (html.escape(row["caller_number"])
              if row["caller_number"] else "(unknown)")
    ftc_href = html.escape(build_fill_script("ftc", af["ftc"]), quote=True)
    fcc_href = html.escape(build_fill_script("fcc", fcc_map), quote=True)
    prefill = html.escape(fcc_map["prefill_url"], quote=True)

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>Report this call (fill-only)</title></head><body>",
        "<h1>Report this robocall</h1>",
        "<p>Caller number: <strong>{}</strong></p>".format(caller),
        "<p>best identifier: {}</p>".format(best_id),
        '<div style="background:#fff3cd;border:1px solid #e0c060;padding:.75rem;">'
        "<strong>FILL-ONLY TOOLS -- NOTHING IS SUBMITTED.</strong>"
        " Every link below only FILLS the official form. Review what it wrote,"
        " clear the CAPTCHA, and submit it yourself."
        "</div>",
        "<h2>1. FCC (zero-JS shortcut)</h2>",
        '<p><a href="{}">Open the FCC Phone form pre-filled</a></p>'.format(
            prefill),
        "<h2>2. Bookmarklets (run while on the live form)</h2>",
        "<ul>",
        '<li><a href="{}">'
        "FTC: fill reportfraud.ftc.gov (open that form first, then click)"
        "</a></li>".format(ftc_href),
        '<li><a href="{}">'
        "FCC: fill consumercomplaints.fcc.gov (open that form first, then click)"
        "</a></li>".format(fcc_href),
        "</ul>",
        "<p>Reminder: NOTHING IS SUBMITTED by any tool on this page.</p>",
        '<p><a href="/complaint/{}">Back to the plain report page</a></p>'.format(
            html.escape(vm_id)),
        '</body></html>',
    ]
    return HTMLResponse("".join(parts))


# --- ingest-screenshots (reference impl) ---
import re as _ss_re


def parse_screenshot_ocr(text):
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    TIME = _ss_re.compile(r"\b(\d{1,2}):(\d{2})\b")

    def digits_of(s):
        d = _ss_re.sub(r"\D", "", s)
        if len(d) == 11 and d.startswith("1"):
            d = d[1:]
        return d

    def is_marker(ln):
        low = ln.lower()
        return (low.startswith("today") or low.startswith("yesterday")
                or bool(_ss_re.match(r"(mon|tue|wed|thu|fri|sat|sun)", low))
                or bool(_ss_re.match(r"\d{1,2}/\d{1,2}", low)))

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
