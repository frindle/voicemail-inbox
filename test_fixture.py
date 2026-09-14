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

    # --- span-tail: the done glyph is a well-formed element immediately
    # followed by the rest of the cell (kills a trailing-junk mutation) ---
    ("mark done glyph is a closed span followed by whitespace",
     lambda: "✓</span> " in mark(1, "fcc_filed"), True),
    ("actions done glyph is a closed span followed by whitespace",
     lambda: "✓</span> " in act(True), True),

    # --- integration: Actions is done ONLY when (ftc AND fcc). A controlled
    # row (no audio / not-done transcript / no screenshots) emits glyphs ONLY
    # from the FTC/FCC/Actions cells, so counts isolate the AND wiring and
    # catch both `and`->`or` and a dropped _actions_cell call. ---
    ("render ftc=1,fcc=0: exactly one green check (FTC only; Actions NOT done)",
     lambda: _row(ftc=1, fcc=0).count(CHECK) == 1, True),
    ("render ftc=1,fcc=0: exactly two red crosses (FCC + Actions)",
     lambda: _row(ftc=1, fcc=0).count(CROSS) == 2, True),
    ("render ftc=1,fcc=1: three green checks (FTC+FCC+Actions), zero crosses",
     lambda: (_row(ftc=1, fcc=1).count(CHECK) == 3) and
             (_row(ftc=1, fcc=1).count(CROSS) == 0), True),
]


def _row(ftc, fcc):
    """One render row whose ONLY glyph-emitting cells are FTC/FCC/Actions:
    no audio (rec empty), status not done/processing (transcript empty),
    no screenshots."""
    return target._render_index([
        {"id": "rr", "created_at": 0, "status": "new", "transcript": None,
         "caller_number": None, "callback_number": None,
         "audio_path": None, "has_screenshots": 0,
         "ftc_filed": ftc, "fcc_filed": fcc}])


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
