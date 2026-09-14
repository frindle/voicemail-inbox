# TASK: vm-phone-and-edit

## Confirmed defect (observed, not suspected)

Confirmed by reading server.py `_render_index`: the From column renders the raw
`caller_number` (e.g. `3218661469`) or a U+2014 dash (L677, L694), and the Callback
column renders the raw `callback_number` or a dash (L678, L695). Two changes:
1. FORMAT a present number as `(xxx) xxx-xxxx` (handle 10-digit and 11-digit with a
   leading country `1`; leave a non-conforming or empty value alone).
2. When a From/Callback value is EMPTY, render an INLINE editable form so the missing
   value can be filled from the front-page table, REUSING the existing
   `POST /complaint/{id}/update` route (server.py L567) -- do NOT invent a new route.

## Entry point

server.py: add two helpers near `_normalize_phone` (L170) / `_mark_cell` (L638), then
wire them into `_render_index` at the From/Callback `<td>` appends (L694-695).

## Required change

1. Add `def _format_phone(value):` that reuses `_normalize_phone(value)`:
   - if the normalized result is exactly 10 digits, return `(xxx) xxx-xxxx`
     (e.g. `3218661469` -> `(321) 866-1469`; `13218661469` -> `(321) 866-1469`;
     `321-866-1469` -> `(321) 866-1469`).
   - otherwise return the ORIGINAL `value` unchanged if it is truthy, else `""`
     (so `abc` -> `abc`, `12345` -> `12345`, `""` -> `""`, `None` -> `""`).

2. Add `def _number_cell(vm_id_esc, field, value, other_field, other_value):` returning
   one `<td>`:
   - if `value` is truthy: `"<td>{}</td>"` with `html.escape(_format_phone(value))`
     (so a present number is FORMATTED and HTML-escaped; no form in this state).
   - if `value` is empty: a `<td>` containing an inline
     `<form method="post" action="/complaint/{id}/update" style="display:inline">`
     with a `<input type="text" name="{field}" ...>` (empty, the editable control),
     a `<button type="submit">Save</button>`, AND a
     `<input type="hidden" name="{other_field}" value="{escaped other_value}">`.
     The hidden field is MANDATORY: `/complaint/{id}/update` overwrites BOTH
     caller_number and callback_number, so without carrying the other field's current
     value a save would WIPE it. Escape `other_value` with `html.escape(..., quote=True)`.

3. In `_render_index`, replace the From `<td>` append (L694) with
   `parts.append(_number_cell(vm_id_esc, "caller_number", it.get("caller_number"), "callback_number", it.get("callback_number")))`
   and the Callback `<td>` append (L695) with
   `parts.append(_number_cell(vm_id_esc, "callback_number", it.get("callback_number"), "caller_number", it.get("caller_number")))`.
   Remove the now-unused `caller =` / `callback =` local assignments at L677-678.

Behaviour that must NOT change:
- `_render_index` still emits one `<tr>` per item, same column order.
- Present numbers are HTML-escaped (no raw injection).
- The empty-cell save posts to the existing `/complaint/{id}/update` route only.

## Must contain

- `_format_phone`
- `_number_cell`
- `/complaint/`
- `type="hidden"`

## Scope

Only edit `server.py`; do not edit `verify.sh`, `test_fixture.py`, `check_literals.py`
or `TASK.md`.

## Keep every changed line exercised (relevance)

`_format_phone` is asserted by exact-equality cases (10/11-digit, dashed, junk, empty,
None); `_number_cell` present/empty branches, the formatted+escaped output, and the
mandatory hidden other-field are all asserted behaviourally by test_fixture.py.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing until it prints `VERIFY_OK`.
