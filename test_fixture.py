"""Adversarial fixture for: vm-status-cells

Tests _mark_cell (FTC/FCC) and _actions_cell (Actions) directly. Importing
server.py runs init_db()/makedirs against ./data -- harmless in the worktree.
"""
import sys
import importlib.util

spec = importlib.util.spec_from_file_location("target", 'server.py')
target = importlib.util.module_from_spec(spec)
spec.loader.exec_module(target)

CROSS = "✗"   # red X, "not done / start process"
CHECK = "✓"   # green check, "done"


def mark(set_flag, flag="ftc_filed"):
    return target._mark_cell(flag, "abc123", set_flag)


def act(done):
    return target._actions_cell("xy9", done)


CASES = [
    # --- _mark_cell NOT done: clickable red cross to report, no green check ---
    ("mark not-done shows the cross glyph",
     lambda: CROSS in mark(0), True),
    ("mark not-done cross is clickable link to the report flow",
     lambda: "/complaint/abc123/report" in mark(0), True),
    ("mark not-done is styled red",
     lambda: "color:#c00" in mark(0), True),
    ("mark not-done must NOT show the green check (wrong-fix guard)",
     lambda: CHECK in mark(0), False),

    # --- _mark_cell done: green check, no cross ---
    ("mark done shows the check glyph",
     lambda: CHECK in mark(1, "fcc_filed"), True),
    ("mark done is styled green",
     lambda: "color:#080" in mark(1, "fcc_filed"), True),
    ("mark done must NOT show the red cross (wrong-fix guard)",
     lambda: CROSS in mark(1, "fcc_filed"), False),

    # --- _mark_cell keeps the mark/unmark toggle in BOTH states ---
    ("mark not-done keeps a toggle posting to /mark",
     lambda: "/complaint/abc123/mark" in mark(0), True),
    ("mark done keeps a toggle posting to /mark",
     lambda: "/complaint/abc123/mark" in mark(1), True),
    ("mark not-done toggle value is the opposite (1) of current (0)",
     lambda: 'name="value" value="1"' in mark(0), True),
    ("mark done toggle value is the opposite (0) of current (1)",
     lambda: 'name="value" value="0"' in mark(1), True),

    # --- _actions_cell NOT done ---
    ("actions not-done shows clickable red cross to report",
     lambda: (CROSS in act(False)) and ("/complaint/xy9/report" in act(False)), True),
    ("actions not-done must NOT show the green check",
     lambda: CHECK in act(False), False),

    # --- _actions_cell done ---
    ("actions done shows green check",
     lambda: CHECK in act(True), True),
    ("actions done must NOT show the red cross",
     lambda: CROSS in act(True), False),

    # --- _actions_cell keeps Delete in both states ---
    ("actions not-done keeps a Delete form to /delete",
     lambda: "/delete/xy9" in act(False), True),
    ("actions done keeps a Delete form to /delete",
     lambda: "/delete/xy9" in act(True), True),

    # --- integration: _render_index wires Actions to (ftc AND fcc) ---
    ("render: item with only ftc filed -> Actions still NOT done (cross present)",
     lambda: CROSS in target._render_index([
         {"id": "r1", "created_at": 0, "status": "done", "transcript": "hi",
          "caller_number": "3218661469", "callback_number": None,
          "audio_path": "/a", "has_screenshots": 0,
          "ftc_filed": 1, "fcc_filed": 0}]), True),
    ("render: item with BOTH ftc and fcc filed -> Actions done (a check appears)",
     lambda: CHECK in target._render_index([
         {"id": "r2", "created_at": 0, "status": "done", "transcript": "hi",
          "caller_number": "3218661469", "callback_number": None,
          "audio_path": "/a", "has_screenshots": 0,
          "ftc_filed": 1, "fcc_filed": 1}]), True),
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
