#!/usr/bin/env python3
"""Reference impl for vm-status-cells (FTC/FCC/TCPA + schema + delete)."""
import pathlib, sys
wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SC = pathlib.Path("/private/tmp/claude-501/-Users-penn-Desktop-GitHub-Projects/25809008-b52f-4110-a02e-82f6c315e9aa/scratchpad")
p = wt / "server.py"
t = p.read_text()

old_mig = '            ("fcc_filed", "INTEGER DEFAULT 0"),\n        ):'
new_mig = ('            ("fcc_filed", "INTEGER DEFAULT 0"),\n'
           '            ("tcpa_filed", "INTEGER DEFAULT 0"),\n        ):')
assert old_mig in t, "migration tuple anchor not found"
t = t.replace(old_mig, new_mig, 1)

old_wl = '_MARK_FLAGS = ("ftc_filed", "fcc_filed")'
new_wl = '_MARK_FLAGS = ("ftc_filed", "fcc_filed", "tcpa_filed")'
assert old_wl in t, "MARK_FLAGS anchor not found"
t = t.replace(old_wl, new_wl, 1)

old_sel = ('            " caller_number, audio_path, has_screenshots, ftc_filed, fcc_filed"\n'
           '            " FROM voicemails ORDER BY created_at DESC"')
new_sel = ('            " caller_number, audio_path, has_screenshots, ftc_filed,"\n'
           '            " fcc_filed, tcpa_filed"\n'
           '            " FROM voicemails ORDER BY created_at DESC"')
assert old_sel in t, "api_list SELECT anchor not found"
t = t.replace(old_sel, new_sel, 1)

old_dict = '            "fcc_filed": r["fcc_filed"],\n'
new_dict = '            "fcc_filed": r["fcc_filed"],\n            "tcpa_filed": r["tcpa_filed"],\n'
assert old_dict in t, "api_list dict anchor not found"
t = t.replace(old_dict, new_dict, 1)

helpers = SC.joinpath("S_helpers.txt").read_text().rstrip("\n")
mstart = "def _mark_cell(flag, vm_id_esc, set_flag):"
mend = ").format(mark=mark, id=vm_id_esc, flag=flag, opposite=opposite)"
i = t.index(mstart)
j = t.index(mend, i) + len(mend)
t = t[:i] + helpers + t[j:]

old_h = '        "<th>FTC</th><th>FCC</th><th>Actions</th>"'
new_h = '        "<th>FTC</th><th>FCC</th><th>TCPA</th><th></th>"'
assert old_h in t, "header anchor not found"
t = t.replace(old_h, new_h, 1)

old_actions = (
    "        parts.append(\n"
    "            '<td><a href=\"/complaint/{id}/report\">Report</a> '\n"
    "            '<form method=\"post\" action=\"/delete/{id}\" '\n"
    "            'onsubmit=\"return confirm(&#39;Delete this voicemail?&#39;);\" '\n"
    "            'style=\"display:inline\">'\n"
    "            '<button type=\"submit\">Delete</button></form></td>'\n"
    "            .format(id=vm_id_esc)\n"
    "        )\n"
)
new_rows = (
    "        parts.append(_tcpa_cell(vm_id_esc, it.get(\"tcpa_filed\")))\n"
    "        parts.append(_delete_cell(vm_id_esc))\n"
)
assert old_actions in t, "per-row Actions anchor not found"
t = t.replace(old_actions, new_rows, 1)

p.write_text(t)
print("refimpl applied")
