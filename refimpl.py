#!/usr/bin/env python3
"""Reference impl for vm-status-cells. Bodies live outside the worktree so a
refimpl-revert restores a clean launch tree."""
import pathlib, sys
wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
SC = pathlib.Path("/private/tmp/claude-501/-Users-penn-Desktop-GitHub-Projects/25809008-b52f-4110-a02e-82f6c315e9aa/scratchpad")
p = wt / "server.py"
t = p.read_text()

new_mark = SC.joinpath("A_mark_cell.txt").read_text().rstrip("\n")
new_actions = SC.joinpath("A_actions_cell.txt").read_text().rstrip("\n")

# 1) Replace the whole existing _mark_cell def, and append _actions_cell after it.
old_mark_start = "def _mark_cell(flag, vm_id_esc, set_flag):"
old_mark_end = ").format(mark=mark, id=vm_id_esc, flag=flag, opposite=opposite)"
i = t.index(old_mark_start)
j = t.index(old_mark_end, i) + len(old_mark_end)
t = t[:i] + new_mark + "\n\n\n" + new_actions + t[j:]

# 2) Replace the inline Actions <td> append with a call to _actions_cell.
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
new_actions_call = (
    "        parts.append(_actions_cell(\n"
    "            vm_id_esc, bool(it.get(\"ftc_filed\") and it.get(\"fcc_filed\"))))\n"
)
assert old_actions in t, "actions anchor not found"
t = t.replace(old_actions, new_actions_call, 1)

p.write_text(t)
print("refimpl applied")
