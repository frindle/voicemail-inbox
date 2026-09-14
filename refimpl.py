#!/usr/bin/env python3
"""Reference impl for vm-pdf-export."""
import pathlib, sys
wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = wt / "server.py"
t = p.read_text()

# 1) Response import
old_imp = "from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse"
new_imp = "from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response"
assert old_imp in t
t = t.replace(old_imp, new_imp, 1)

# 2) the export route, inserted before /healthz
route = '''@app.get("/export/pdf")
def export_pdf(authorization: str = Header(default=None)):
    _check_auth(authorization)
    import io
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    rows = api_list()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    y = 750
    c.setFont("Helvetica-Bold", 13)
    c.drawString(40, y, "Voicemail call log")
    y -= 26
    c.setFont("Helvetica", 9)
    for r in rows:
        d, tm = _ymd_hm(r.get("created_at"))
        line = "{} {}  From: {}  Callback: {}".format(
            d, tm, r.get("caller_number") or "-",
            r.get("callback_number") or "-")
        c.drawString(40, y, line[:120])
        y -= 14
        if y < 40:
            c.showPage()
            y = 750
            c.setFont("Helvetica", 9)
    c.showPage()
    c.save()
    pdf = buf.getvalue()
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition":
                             "attachment; filename=call-log.pdf"})


'''
anchor = '@app.get("/healthz")'
i = t.index(anchor)
t = t[:i] + route + t[i:]

# 3) front-page link
old_h1 = '        "<h1>Voicemails</h1>",'
new_h1 = '        "<h1>Voicemails</h1>",\n        \'<p><a href="/export/pdf">Export PDF</a></p>\','
assert old_h1 in t
t = t.replace(old_h1, new_h1, 1)

p.write_text(t)

# 4) requirements.txt
rq = wt / "requirements.txt"
rt = rq.read_text()
if "reportlab" not in rt:
    if not rt.endswith("\n"):
        rt += "\n"
    rt += "reportlab==4.4.9\n"
    rq.write_text(rt)
print("refimpl applied")
