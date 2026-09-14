# TASK: vm-status-cells

## Confirmed defect (observed, not suspected)

Confirmed by reading server.py: the front-page table's FTC and FCC cells are built by
`_mark_cell` (server.py L638-650) which renders `{mark} <a ...>Report</a>` plus a
`<button>toggle</button>` form; the Actions cell is built inline in `_render_index`
(L701-708) as `<a ...>Report</a>` + a `<button>Delete</button>` form. Penn wants these
three columns to be CLICKABLE STATUS INDICATORS instead:
- NOT done  -> a red clickable mark (glyph U+2717 "cross") the user clicks to START that
  column's process (its filing/report flow at /complaint/{id}/report).
- done      -> a green mark (glyph U+2713 "check").
A way to mark/unmark done must remain, and the Delete affordance must remain.

## Entry point

server.py:638 (`_mark_cell`) and the Actions `<td>` in `_render_index` (server.py:701-708).

## Required change

1. Rewrite `_mark_cell(flag, vm_id_esc, set_flag)` so that:
   - when `set_flag` is falsy: the cell shows a CLICKABLE red cross that links to
     `/complaint/{id}/report` and is styled `color:#c00`; the cross glyph is U+2717.
     The cell must NOT contain the green-check glyph U+2713 in this state.
   - when `set_flag` is truthy: the cell shows a green check (glyph U+2713) styled
     `color:#080`; the cell must NOT contain the cross glyph U+2717 in this state.
   - in BOTH states, keep the existing toggle form posting to
     `/complaint/{id}/mark` (so done can be set/unset), with the hidden `flag` and a
     hidden `value` equal to the OPPOSITE of the current 0/1 state.

2. Add a helper `def _actions_cell(vm_id_esc, done):` that returns the Actions `<td>`:
   - when `done` is falsy: a clickable red cross (U+2717, `color:#c00`) linking to
     `/complaint/{id}/report`; must NOT contain U+2713.
   - when `done` is truthy: a green check (U+2713, `color:#080`); must NOT contain U+2717.
   - in BOTH states keep the Delete form posting to `/delete/{id}` (a `<button>` labelled
     Delete), so a voicemail can still be deleted.
   Then in `_render_index`, replace the inline Actions `<td>` (L701-708) with:
   `parts.append(_actions_cell(vm_id_esc, bool(it.get("ftc_filed") and it.get("fcc_filed"))))`
   i.e. Actions is "done" only when BOTH ftc_filed AND fcc_filed are set.

Behaviour that must NOT change:
- The FTC/FCC toggle still posts flag + opposite-value to /complaint/{id}/mark.
- Delete still posts to /delete/{id}.
- `_render_index` still emits one `<tr>` per item with the same column order.
- `vm_id_esc` is already HTML-escaped by the caller; do not double-escape it.

## Must contain

- `_actions_cell`
- `color:#c00`
- `color:#080`
- `/complaint/`
- `/delete/`

## Scope

Only edit `server.py`; do not edit `verify.sh`, `test_fixture.py`, `check_literals.py`
or `TASK.md`. test_fixture.py is the test fixture -- changing it invalidates the check.

## Keep every changed line exercised (relevance)

The color constants (`color:#c00`, `color:#080`) are asserted by check_literals; the
glyphs, the report/delete links, and the toggle form are asserted behaviourally by
test_fixture.py calling `_mark_cell` and `_actions_cell` directly. Do not add lone
untested lines.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing until it prints `VERIFY_OK`.
