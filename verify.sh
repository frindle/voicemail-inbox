#!/usr/bin/env bash
# verify for: voicemail-onecontainer
# Counting idiom, NOT `set -e` -- an aborting verify never prints why it failed.
cd "$(dirname "$0")" || exit 1

fails=0

# --- env parity ------------------------------------------------------------
# The fixture parses docker-compose.yml with PyYAML and parses
# supervisord.conf with the stdlib configparser. PyYAML is not stdlib, so
# bootstrap a venv the same way every other verify in this repo does.
PY=.venv/bin/python
if [ ! -x "$PY" ]; then
  python3 -m venv .venv >/dev/null 2>&1 \
    && .venv/bin/pip install -q pyyaml >/dev/null 2>&1
fi
[ -x "$PY" ] || PY=python3

echo "=== Dockerfile.whisper removed ==="
if [ -f Dockerfile.whisper ]; then
  echo "  FAIL: Dockerfile.whisper still present -- must be deleted, absorbed into Dockerfile+supervisord.conf"
  fails=$((fails+1))
else
  echo "  ok: Dockerfile.whisper absent"
fi

echo "=== server.py / worker.py untouched ==="
if git diff --quiet HEAD -- server.py worker.py 2>/dev/null; then
  echo "  ok: server.py and worker.py unchanged"
else
  echo "  FAIL: server.py or worker.py was edited -- out of scope"
  fails=$((fails+1))
fi

echo "=== spec literals ==="
if "$PY" ./check_literals.py; then
  echo "  ok: every Must-contain literal present"
else
  echo "  FAIL: a Must-contain literal is missing"; fails=$((fails+1))
fi

echo "=== structural / behavioural cases ==="
if "$PY" ./test_fixture.py; then
  echo "  ok: adversarial cases pass"
else
  echo "  FAIL: adversarial cases failed"; fails=$((fails+1))
fi

echo "--- $fails failed ---"
[ "$fails" -eq 0 ] && echo VERIFY_OK || exit 1
