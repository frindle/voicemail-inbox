#!/usr/bin/env python3
# Reference impl: copy the pre-authored answer (kept outside the worktree so the
# model never starts from it) over server.py. The gate reverts server.py after.
import shutil, sys, os
wt = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.abspath(__file__))
BODY = "/private/tmp/claude-501/-Users-penn-Desktop-GitHub-Projects/25809008-b52f-4110-a02e-82f6c315e9aa/scratchpad/answer_server.py"
shutil.copyfile(BODY, os.path.join(wt, "server.py"))
print("refimpl: wrote server.py from", BODY)
