#!/usr/bin/env python3
"""Reference impl for vm-pdf-export."""
import pathlib, sys
wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = wt / "server.py"
t = p.read_text()

old_imp = "from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse"
new_imp = old_imp + ", Response"
assert old_imp in t
t = t.replace(old_imp, new_imp, 1)

route = '''@app.get("/export/pdf")
def export_pdf(authorization: str = Header(default=None)):
    _check_auth(authorization)
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    rows = api_list()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter, pageCompression=0)
    text = c.beginText(40, 750)  # relevance: unobservable (pixel layout)
    text.setFont("Helvetica", 10)  # relevance: unobservable (font choice)
    text.textLine("Voicemail call log")
    for r in rows:
        d, tm = _ymd_hm(r.get("created_at"))
        text.textLine("{} {}  From: {}  Callback: {}".format(
            d, tm, r.get("caller_number") or "-",
            r.get("callback_number") or "-"))
    c.drawText(text)
    c.showPage()  # relevance: unobservable (page flush)
    c.save()
    pdf = buf.getvalue()
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             "attachment; filename=call-log.pdf"})


'''
anchor = '@app.get("/healthz")'
i = t.index(anchor)
t = t[:i] + route + t[i:]

old_h1 = '        "<h1>Voicemails</h1>",'
new_h1 = old_h1 + '\n        \'<p><a href="/export/pdf">Export PDF</a></p>\','
assert old_h1 in t
t = t.replace(old_h1, new_h1, 1)
p.write_text(t)

rq = wt / "requirements.txt"
rt = rq.read_text()
if "reportlab" not in rt:
    if not rt.endswith("\n"):
        rt += "\n"
    rt += "reportlab==4.4.9\n"
    rq.write_text(rt)
print("refimpl applied")
