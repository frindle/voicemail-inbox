# TASK: vm-pdf-export

## Confirmed defect (observed, not suspected)

Confirmed by reading server.py: the app exposes the call log as JSON (`/api/list`,
L374) and as an HTML table (`_render_index`, L653) but there is NO way to export the
call log as a PDF. Penn wants an endpoint (and a button on the front page) to export
the voicemail/call-log table as a PDF. It must be auth-gated with `_check_auth`
(server.py L92) like the other routes, and requires a PDF library (`reportlab`) added
to `requirements.txt`.

## Entry point

server.py: add a new `@app.get("/export/pdf")` route (near the other routes, e.g. by
`/healthz` L726). Add `reportlab` to `requirements.txt`. Add a link to `/export/pdf`
in `_render_index` (near the `<table>` / `<h1>Voicemails</h1>`, L665-666).

## Required change

1. In `requirements.txt`, add a pinned `reportlab==4.4.9` line.

2. Add a route `def export_pdf(authorization: str = Header(default=None)):` decorated
   `@app.get("/export/pdf")` that:
   - calls `_check_auth(authorization)` FIRST (so the AUTH_TOKEN env var gates it
     exactly like /api/complaint etc.: no/invalid bearer -> 401 when AUTH_TOKEN is set).
   - builds a PDF of the call log from `api_list()` using `reportlab` (e.g.
     `reportlab.pdfgen.canvas.Canvas` writing to an `io.BytesIO`), drawing a title and
     one line per voicemail (date/time from `_ymd_hm`, the raw `caller_number` and
     `callback_number`).
   - returns the PDF bytes with media type `application/pdf` (use
     `fastapi.responses.Response(content=..., media_type="application/pdf")`; add
     `Response` to the existing `from fastapi.responses import ...` line). Include a
     `Content-Disposition: attachment; filename=call-log.pdf` header.

3. In `_render_index`, add a visible link/button to `/export/pdf` (e.g.
   `<p><a href="/export/pdf">Export PDF</a></p>`) near the page heading.

Behaviour that must NOT change:
- Existing routes and `_render_index` columns are unchanged.
- The endpoint must NEVER submit or mutate anything; it only reads and renders.
- Use only the standard lib + reportlab + fastapi (already deps).

## Environment

- `AUTH_TOKEN` (server.py L21): when set, `_check_auth` requires `Authorization: Bearer
  <AUTH_TOKEN>`; the verify sets it to test the 401/200 gate.

## Must contain

- `/export/pdf`
- `application/pdf`
- `_check_auth`
- in requirements.txt: `reportlab`

## Scope

Only edit `server.py` and `requirements.txt`; do not edit `verify.sh`,
`test_fixture.py`, `check_literals.py` or `TASK.md`.

## Keep every changed line exercised (relevance)

The route, its `application/pdf` media type, the `%PDF` output, and the `_check_auth`
gate (401 without a token, 200 with) are all asserted behaviourally by test_fixture.py
driving a FastAPI TestClient; the `reportlab` requirement is asserted by check_literals.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing until it prints `VERIFY_OK`.
