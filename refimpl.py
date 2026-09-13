#!/usr/bin/env python3
"""Reference impl for: voicemail-ui-s1-schema

The gate applies this, runs the verify, and reverts it. It proves two things at
once: the task is SATISFIABLE as specified, and the verify actually ENFORCES
the spec (a refimpl that goes green while a "Must contain" literal is absent
means the verify is benign).

Write the SIMPLEST change that makes the verify pass. It doubles as your review
reference when the model's diff comes back.
"""
import pathlib
import sys

wt = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
p = wt / 'server.py'
t = p.read_text()

OLD = """            ("progress", "INTEGER"),
        ):"""
NEW = """            ("progress", "INTEGER"),
            ("screenshot_ingested", "INTEGER DEFAULT 0"),
            ("screenshot_paths", "TEXT"),
            ("ov_vm", "INTEGER"),
            ("ov_shot", "INTEGER"),
            ("ov_ftc", "INTEGER"),
            ("ov_fcc", "INTEGER"),
            ("ov_tcpa", "INTEGER"),
        ):"""

assert OLD in t, "refimpl anchor not found -- did the target change?"
p.write_text(t.replace(OLD, NEW, 1))
print("refimpl applied")
