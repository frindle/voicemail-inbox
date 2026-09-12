# TASK: voicemail-onecontainer

## Confirmed defect (observed, not suspected)

confirmed: voicemail-inbox currently ships as TWO containers -- `voicemail-inbox`
(FastAPI app, Dockerfile, :8000) and `voicemail-whisper` (faster-whisper
worker, Dockerfile.whisper, joined to the app's network namespace via
`network_mode: "service:voicemail-inbox"` in docker-compose.yml). Verified by
reading docker-compose.yml: two `services:` entries, two Dockerfiles. Penn's
standard (already applied to resell-tracker) is ONE container per project.

## Entry point

Dockerfile:1 (replace), plus new supervisord.conf, rewritten
docker-compose.yml, merged requirements.txt, and deletion of
Dockerfile.whisper.

## Required change

Merge the app and the whisper worker into a SINGLE container, running BOTH
processes under `supervisord` -- mirroring the resell-tracker
`Dockerfile.all-in-one` + `docker/supervisord.conf` pattern (one apt
transaction for system deps, one `pip install`, one `[supervisord]` block
with `nodaemon=true`, one `[program:*]` section per process, each program's
stdout pointed at `/dev/fd/1` with `stdout_logfile_maxbytes=0` so
`docker logs` shows everything, `autorestart=true` on every program).

### 1. `Dockerfile` (replace entirely; base stays `python:3.12-slim`)
- `apt-get update && apt-get install -y --no-install-recommends ffmpeg supervisor`
  then `rm -rf /var/lib/apt/lists/*` in the SAME RUN layer (one apt
  transaction, cache cleaned -- do not split into two RUNs).
- `COPY requirements.txt .` then `RUN pip install --no-cache-dir -r requirements.txt`
  BEFORE copying the app code (Docker layer caching -- an app edit must not
  invalidate the dependency layer).
- `ENV DATA_DIR=/data` and `ENV WHISPER_MODEL_DIR=/models`.
- `VOLUME ["/data", "/models"]` -- BOTH paths, one instruction.
- `COPY server.py worker.py supervisord.conf .` -- all three files, one
  instruction, after the pip install layer.
- `EXPOSE 8000`.
- Keep the existing `HEALTHCHECK` (python urllib GET of `http://127.0.0.1:8000/`,
  `--interval=30s --timeout=5s --start-period=10s`).
- `CMD ["supervisord", "-c", "/app/supervisord.conf"]` -- supervisord is now
  PID 1's child, not uvicorn directly.
- Do NOT bake `AUTH_TOKEN` into the image (no `ENV AUTH_TOKEN=` line at all --
  it stays a docker-compose-supplied secret, same as today).
- The existing non-root `USER appuser` step is dropped: supervisord manages
  two processes and needs to run as root the same way the resell-tracker
  all-in-one container's supervisord does (`user=root` in
  `[supervisord]`) -- do not carry the `useradd`/`USER appuser` lines forward.

### 2. `supervisord.conf` (NEW file, ini format, lives at repo root)
Two programs, both `autorestart=true`, both logging to `/dev/fd/1`
(`stdout_logfile=/dev/fd/1`, `stdout_logfile_maxbytes=0`,
`redirect_stderr=true`) so everything lands in `docker logs` as one stream:
- `[supervisord]` section: `nodaemon=true` (required -- without it supervisord
  daemonizes and the container exits immediately since nothing holds PID 1
  in the foreground).
- `[program:app]`: `command=uvicorn server:app --host 0.0.0.0 --port 8000`,
  `directory=/app`.
- `[program:whisper]`: `command=python worker.py`, `directory=/app`. Give it
  a first-run-download-tolerant `startsecs` (>= 20) and `startretries` (>= 5)
  -- faster-whisper downloads the model into `/models` on its first start and
  a short `startsecs` would flap it FATAL mid-download.
- Also include `[unix_http_server]`, `[rpcinterface:supervisor]` and
  `[supervisorctl]` sections (mirrors the resell-tracker conf, gives
  `docker exec -it voicemail-inbox supervisorctl status` for free) -- not
  load-bearing for the two programs above but keep the file a complete,
  valid supervisord config.

### 3. `docker-compose.yml` (rewrite to ONE service)
- Exactly one service, named `voicemail-inbox`, `build: .` (the merged
  Dockerfile -- no `dockerfile:` override needed since there is only one
  Dockerfile now).
- Keep the br0 macvlan networking EXACTLY as today: `networks: br0:
  ipv4_address: 10.0.12.44` and `mac_address: "02:42:0A:00:0C:2C"` (pinned MAC
  -- an unpinned one gets Firewalla-quarantined on every recreate).
  `networks: br0: external: true, name: br0` at the top level.
  Do not change the IP or MAC.
- `environment:` keeps `DATA_DIR=/data` and `AUTH_TOKEN=${AUTH_TOKEN}` (the
  only secret, LAN-open when unset -- do not add a default/fallback value).
- `volumes:` needs BOTH host paths mapped in, as two separate volume lines:
  `/mnt/user/data/Documents/Voicemail:/data` (unchanged) AND
  `/mnt/user/data/Documents/Voicemail/whisper-models:/models` (moved over
  from the old `voicemail-whisper` service, unchanged path).
- Keep the existing `healthcheck:` block (same python urllib CMD,
  interval/timeout/start_period/retries as today) and the
  `labels: net.unraid.docker.icon:` line, and `restart: unless-stopped`.
- REMOVE entirely: the second `voicemail-whisper` service block, its
  `network_mode: "service:voicemail-inbox"` key, its `depends_on:`, and its
  `VOICEMAIL_URL`/`WHISPER_MODEL` env vars (WHISPER_MODEL can move to the
  merged service's environment if you want it configurable, but it is NOT
  required -- worker.py already defaults `WHISPER_MODEL=small.en`).
- Keep the top-level `networks: br0: external: true` block exactly as today.

### 4. `requirements.txt` (merge both images' deps)
Union of what the current `Dockerfile` installs (fastapi, uvicorn[standard],
python-multipart, httpx -- keep their exact pinned versions from the current
file) AND what `Dockerfile.whisper` installs via
`pip install faster-whisper requests` (pin BOTH: `faster-whisper` and
`requests` each need an explicit `==` version pin, matching this repo's
style of every other line in requirements.txt -- do not leave either
unpinned).

### 5. Delete `Dockerfile.whisper`
It is fully absorbed into the merged `Dockerfile` + `supervisord.conf`. Use
`git rm Dockerfile.whisper` (or plain `rm` -- the change is staged/committed
by the harness, not by you).

Behaviour that must NOT change:
- `server.py` and `worker.py` are NOT edited. `worker.py`'s default
  `VOICEMAIL_URL=http://127.0.0.1:8000` already reaches the app because both
  processes now share one container's network namespace -- nothing about
  worker.py needs to change for that to keep working.
- The app still serves on :8000, healthcheck still targets `/`.
- Auth stays LAN-open when `AUTH_TOKEN` is unset (do not add a default token
  value or make it required).

## Must contain

- in Dockerfile: `apt-get install -y --no-install-recommends ffmpeg supervisor`
- in Dockerfile: `COPY server.py worker.py supervisord.conf .`
- in Dockerfile: `VOLUME ["/data", "/models"]`
- in Dockerfile: `CMD ["supervisord", "-c", "/app/supervisord.conf"]`
- in supervisord.conf: `nodaemon=true`
- in supervisord.conf: `[program:app]`
- in supervisord.conf: `uvicorn server:app --host 0.0.0.0 --port 8000`
- in supervisord.conf: `[program:whisper]`
- in supervisord.conf: `python worker.py`
- in supervisord.conf: `autorestart=true`
- in docker-compose.yml: `10.0.12.44`
- in docker-compose.yml: `02:42:0A:00:0C:2C`
- in docker-compose.yml: `/mnt/user/data/Documents/Voicemail/whisper-models:/models`
- in requirements.txt: `faster-whisper`
- in requirements.txt: `requests`

(The gate holds the reference impl against this list. If the verify goes green
while one of these is absent from the changed files, the verify does not
enforce the spec -- that is a benign verify, caught mechanically.)

## Scope

Edit ONLY these files: `Dockerfile`, `supervisord.conf` (new),
`docker-compose.yml`, `requirements.txt`. Delete `Dockerfile.whisper`.
Do NOT edit `server.py`, `worker.py`, `verify.sh`, `test_fixture.py`,
`check_literals.py`, `refimpl.py`, or `TASK.md`.

## Keep every changed line exercised (relevance)

After the job runs, a mutation check flips/deletes each line you changed and
asks the verify to catch it. Do not add stray unasserted lines -- every
program/volume/env line above is checked by the fixture's structural parse,
so keep to exactly the sections and lines specified.

## Loop instruction

Run `bash verify.sh` after every edit and keep editing until it prints
`VERIFY_OK`. Only edit the files named in Scope.
