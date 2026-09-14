#!/usr/bin/env python3
"""Reference impl for vm-phone-and-edit."""
import pathlib, sys
wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SC = pathlib.Path("/private/tmp/claude-501/-Users-penn-Desktop-GitHub-Projects/25809008-b52f-4110-a02e-82f6c315e9aa/scratchpad")
p = wt / "server.py"
t = p.read_text()

helpers = SC.joinpath("B_helpers.txt").read_text().rstrip("\n")

# Insert the two helpers just before _render_index.
anchor = "def _render_index(items):"
i = t.index(anchor)
t = t[:i] + helpers + "\n\n\n" + t[i:]

# Remove the now-dead caller/callback local assignments.
dead = (
    '        caller = html.escape(it.get("caller_number") or "") or "\u2014"\n'
    '        callback = html.escape(it.get("callback_number") or "") or "\u2014"\n'
)
assert dead in t, "dead-assign anchor not found"
t = t.replace(dead, "", 1)

# Wire the From/Callback cells through _number_cell.
old_from = '        parts.append("<td>{}</td>".format(caller))\n'
old_cb = '        parts.append("<td>{}</td>".format(callback))\n'
new_from = ('        parts.append(_number_cell(vm_id_esc, "caller_number",\n'
            '            it.get("caller_number"), "callback_number",\n'
            '            it.get("callback_number")))\n')
new_cb = ('        parts.append(_number_cell(vm_id_esc, "callback_number",\n'
          '            it.get("callback_number"), "caller_number",\n'
          '            it.get("caller_number")))\n')
assert old_from in t and old_cb in t, "from/callback append anchors not found"
t = t.replace(old_from, new_from, 1).replace(old_cb, new_cb, 1)

p.write_text(t)
print("refimpl applied")
