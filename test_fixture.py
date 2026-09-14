"""Adversarial fixture for: vm-phone-and-edit"""
import sys
import importlib.util

spec = importlib.util.spec_from_file_location("target", 'server.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)


def cell(field, value, other_field, other_value):
    return target._number_cell("abc123", field, value, other_field, other_value)


def render(caller, callback):
    return target._render_index([
        {"id": "rr", "created_at": 0, "status": "new", "transcript": None,
         "caller_number": caller, "callback_number": callback,
         "audio_path": None, "has_screenshots": 0,
         "ftc_filed": 0, "fcc_filed": 0}])


CASES = [
    # --- _format_phone ---
    ("10-digit formats", lambda: target._format_phone("3218661469"), "(321) 866-1469"),
    ("11-digit leading 1 formats", lambda: target._format_phone("13218661469"), "(321) 866-1469"),
    ("dashed 10-digit formats", lambda: target._format_phone("321-866-1469"), "(321) 866-1469"),
    ("already-formatted normalizes back to formatted", lambda: target._format_phone("(321) 866-1469"), "(321) 866-1469"),
    ("non-conforming junk left as-is", lambda: target._format_phone("abc"), "abc"),
    ("too-short number left as-is", lambda: target._format_phone("12345"), "12345"),
    ("empty string -> empty string", lambda: target._format_phone(""), ""),
    ("None -> empty string", lambda: target._format_phone(None), ""),

    # --- _number_cell PRESENT branch: formatted, escaped, no form ---
    ("present number is formatted in the cell",
     lambda: "(321) 866-1469" in cell("caller_number", "3218661469", "callback_number", None), True),
    ("present cell has NO inline form (wrong-fix guard)",
     lambda: "<form" in cell("caller_number", "3218661469", "callback_number", None), False),
    ("present junk value is HTML-escaped (XSS guard)",
     lambda: "&lt;x&gt;" in cell("caller_number", "<x>", "callback_number", None), True),
    ("present junk value is NOT rendered raw",
     lambda: "<x>" in cell("caller_number", "<x>", "callback_number", None), False),

    # --- _number_cell EMPTY branch: editable + save form to /update ---
    ("empty cell renders an editable text input for the field",
     lambda: ('type="text"' in cell("caller_number", "", "callback_number", None))
             and ('name="caller_number"' in cell("caller_number", "", "callback_number", None)), True),
    ("empty cell posts to the existing /update route",
     lambda: '/complaint/abc123/update' in cell("caller_number", "", "callback_number", None), True),
    ("empty cell has a Save control",
     lambda: "Save" in cell("caller_number", "", "callback_number", None), True),

    # --- data-loss guard: the OTHER field is preserved as a hidden input ---
    ("empty From cell carries the current Callback as a hidden field",
     lambda: ('type="hidden"' in cell("caller_number", "", "callback_number", "5551234567"))
             and ('name="callback_number"' in cell("caller_number", "", "callback_number", "5551234567"))
             and ('5551234567' in cell("caller_number", "", "callback_number", "5551234567")), True),
    ("empty Callback cell carries the current From as a hidden field",
     lambda: ('type="hidden"' in cell("callback_number", "", "caller_number", "3218661469"))
             and ('name="caller_number"' in cell("callback_number", "", "caller_number", "3218661469")), True),
    ("hidden other-value is HTML-escaped (quote-safe)",
     lambda: '&quot;' in cell("caller_number", "", "callback_number", 'a"b'), True),

    # --- integration through _render_index: BOTH columns formatted + editable ---
    ("render: present caller is formatted in the page",
     lambda: "(321) 866-1469" in render("3218661469", None), True),
    ("render: present callback is ALSO formatted (not just From)",
     lambda: "(555) 123-4567" in render(None, "5551234567"), True),
    ("render: empty caller yields an inline /update save form",
     lambda: "/complaint/rr/update" in render(None, "5551234567"), True),
    ("render: empty caller form preserves the present callback as hidden",
     lambda: ('type="hidden"' in render(None, "5551234567"))
             and ('name="callback_number"' in render(None, "5551234567")), True),
]


def main():
    if len(CASES) < 3:
        print("  SCAFFOLD_INCOMPLETE"); return 1
    fails = 0
    for desc, thunk, want in CASES:
        try:
            got = thunk()
        except Exception as e:
            print("  FAIL {} -- raised {}: {}".format(desc, type(e).__name__, e)); fails += 1; continue
        if got != want:
            print("  FAIL {} -- got {!r}, want {!r}".format(desc, got, want)); fails += 1
    print("  {}/{} case(s) passed".format(len(CASES) - fails, len(CASES)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
