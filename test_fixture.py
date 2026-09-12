"""Adversarial fixture for: voicemail-onecontainer

Structural checks over Dockerfile (text), supervisord.conf (configparser),
docker-compose.yml (yaml.safe_load), requirements.txt (text) -- these are
config/infra artifacts, not importable Python, so each case parses the real
file and asserts a real structural/behavioural property. Every case is
designed so a plausible WRONG merge (e.g. keeping two services, forgetting
the /models volume, forgetting to pin AUTH_TOKEN out of the image, forgetting
autorestart) fails it.
"""
import configparser
import pathlib
import re
import sys

try:
    import yaml
except ImportError:
    print("  FAIL: PyYAML not installed in verify venv")
    sys.exit(1)


def _dockerfile():
    return pathlib.Path("Dockerfile").read_text()


def _compose():
    return yaml.safe_load(pathlib.Path("docker-compose.yml").read_text())


def _supervisord():
    cp = configparser.ConfigParser(strict=False)
    cp.read("supervisord.conf")
    return cp


def _requirements():
    return pathlib.Path("requirements.txt").read_text()


# ---- Dockerfile cases -------------------------------------------------

def case_dockerfile_single_base_and_ffmpeg_supervisor():
    t = _dockerfile()
    froms = re.findall(r"^FROM\s+(\S+)", t, re.M)
    assert len(froms) == 1, "expected exactly one FROM (single slim base), got {}".format(froms)
    assert "slim" in froms[0], "base image must stay a slim image, got {!r}".format(froms[0])
    assert "ffmpeg" in t and "supervisor" in t, "must install both ffmpeg and supervisor"
    return True


def case_dockerfile_copies_all_three_and_no_baked_token():
    t = _dockerfile()
    assert "server.py" in t and "worker.py" in t and "supervisord.conf" in t, \
        "must COPY server.py, worker.py AND supervisord.conf into the image"
    assert not re.search(r"^\s*ENV\s+AUTH_TOKEN\s*=", t, re.M), \
        "AUTH_TOKEN must never be baked into the image"
    return True


def case_dockerfile_volumes_and_expose_and_cmd():
    t = _dockerfile()
    assert re.search(r"VOLUME\s*\[.*[\"']/data[\"'].*[\"']/models[\"']", t) or \
        re.search(r"VOLUME\s*\[.*[\"']/models[\"'].*[\"']/data[\"']", t), \
        "VOLUME must declare BOTH /data and /models"
    assert re.search(r"^EXPOSE\s+8000\b", t, re.M), "must EXPOSE 8000"
    assert re.search(r"CMD\s*\[.*supervisord.*\]", t), \
        "CMD must run supervisord, not uvicorn directly"
    return True


# ---- supervisord.conf cases --------------------------------------------

def case_supervisord_nodaemon_and_two_programs():
    cp = _supervisord()
    assert cp.has_section("supervisord"), "missing [supervisord] section"
    assert cp.get("supervisord", "nodaemon", fallback="").strip().lower() == "true", \
        "[supervisord] must set nodaemon=true or the container exits immediately"
    prog_sections = [s for s in cp.sections() if s.startswith("program:")]
    assert len(prog_sections) >= 2, "need at least 2 [program:*] sections, got {}".format(prog_sections)
    return True


def case_supervisord_app_program_runs_uvicorn_on_0000_8000():
    cp = _supervisord()
    assert cp.has_section("program:app"), "missing [program:app]"
    cmd = cp.get("program:app", "command", fallback="")
    assert "uvicorn" in cmd and "server:app" in cmd, \
        "app program must run uvicorn server:app, got {!r}".format(cmd)
    assert "0.0.0.0" in cmd and "8000" in cmd, \
        "app program must bind 0.0.0.0:8000, got {!r}".format(cmd)
    assert cp.get("program:app", "autorestart", fallback="").strip().lower() == "true", \
        "[program:app] must set autorestart=true"
    return True


def case_supervisord_whisper_program_runs_worker():
    cp = _supervisord()
    assert cp.has_section("program:whisper"), "missing [program:whisper]"
    cmd = cp.get("program:whisper", "command", fallback="")
    assert "worker.py" in cmd, "whisper program must run worker.py, got {!r}".format(cmd)
    assert cp.get("program:whisper", "autorestart", fallback="").strip().lower() == "true", \
        "[program:whisper] must set autorestart=true"
    return True


# ---- docker-compose.yml cases ------------------------------------------

def case_compose_exactly_one_service():
    doc = _compose()
    services = doc.get("services", {})
    assert len(services) == 1, "expected exactly ONE service, got {}: {}".format(
        len(services), list(services))
    name = next(iter(services))
    assert name == "voicemail-inbox", "the single service must be named voicemail-inbox, got {!r}".format(name)
    return True


def case_compose_no_network_mode_and_builds_dot():
    doc = _compose()
    svc = doc["services"]["voicemail-inbox"]
    assert "network_mode" not in svc, "network_mode must be gone -- both processes share ONE container now"
    build = svc.get("build")
    assert build == "." or (isinstance(build, dict) and build.get("context") == "."), \
        "must build from '.' (the merged Dockerfile), got {!r}".format(build)
    return True


def case_compose_networking_pinned():
    doc = _compose()
    svc = doc["services"]["voicemail-inbox"]
    nets = svc.get("networks", {})
    assert isinstance(nets, dict) and "br0" in nets, "must use br0 macvlan network"
    assert nets["br0"].get("ipv4_address") == "10.0.12.44", \
        "must keep the pinned static IP 10.0.12.44, got {!r}".format(nets["br0"].get("ipv4_address"))
    assert svc.get("mac_address") == "02:42:0A:00:0C:2C", \
        "must keep the pinned MAC 02:42:0A:00:0C:2C, got {!r}".format(svc.get("mac_address"))
    return True


def case_compose_both_volumes_present():
    doc = _compose()
    svc = doc["services"]["voicemail-inbox"]
    vols = svc.get("volumes", [])
    joined = "\n".join(vols)
    assert "/mnt/user/data/Documents/Voicemail:/data" in joined, \
        "missing /data volume mapping, got {!r}".format(vols)
    assert "/mnt/user/data/Documents/Voicemail/whisper-models:/models" in joined, \
        "missing /models volume mapping (absorbed from the old whisper service), got {!r}".format(vols)
    return True


def case_compose_healthcheck_and_external_network_intact():
    doc = _compose()
    svc = doc["services"]["voicemail-inbox"]
    assert "healthcheck" in svc, "healthcheck must survive the merge"
    top_nets = doc.get("networks", {})
    assert top_nets.get("br0", {}).get("external") in (True, "true"), \
        "top-level br0 network must stay external"
    return True


# ---- requirements.txt cases ---------------------------------------------

def case_requirements_merged_and_pinned():
    t = _requirements()
    for pkg in ("fastapi", "uvicorn", "faster-whisper", "requests"):
        assert re.search(r"^{}(\[[^\]]*\])?==".format(re.escape(pkg)), t, re.M), \
            "{} must be present and version-pinned in requirements.txt".format(pkg)
    return True


CASES = [
    ("Dockerfile: single slim base + ffmpeg + supervisor", case_dockerfile_single_base_and_ffmpeg_supervisor, True),
    ("Dockerfile: copies server.py+worker.py+supervisord.conf, no baked AUTH_TOKEN", case_dockerfile_copies_all_three_and_no_baked_token, True),
    ("Dockerfile: VOLUME /data+/models, EXPOSE 8000, CMD supervisord", case_dockerfile_volumes_and_expose_and_cmd, True),
    ("supervisord.conf: nodaemon=true, >=2 program sections", case_supervisord_nodaemon_and_two_programs, True),
    ("supervisord.conf: [program:app] runs uvicorn 0.0.0.0:8000, autorestart", case_supervisord_app_program_runs_uvicorn_on_0000_8000, True),
    ("supervisord.conf: [program:whisper] runs worker.py, autorestart", case_supervisord_whisper_program_runs_worker, True),
    ("docker-compose.yml: exactly one service voicemail-inbox", case_compose_exactly_one_service, True),
    ("docker-compose.yml: no network_mode, builds .", case_compose_no_network_mode_and_builds_dot, True),
    ("docker-compose.yml: pinned br0 IP + MAC", case_compose_networking_pinned, True),
    ("docker-compose.yml: both /data and /models volumes", case_compose_both_volumes_present, True),
    ("docker-compose.yml: healthcheck + external br0 intact", case_compose_healthcheck_and_external_network_intact, True),
    ("requirements.txt: fastapi/uvicorn/faster-whisper/requests all pinned", case_requirements_merged_and_pinned, True),
]


def main():
    if len(CASES) < 3:
        print("  SCAFFOLD_INCOMPLETE: {} adversarial case(s) authored, need >= 3."
              .format(len(CASES)))
        return 1
    fails = 0
    for desc, thunk, want in CASES:
        try:
            got = thunk()
        except Exception as e:
            print("  FAIL {} -- raised {}: {}".format(desc, type(e).__name__, e))
            fails += 1
            continue
        if got != want:
            print("  FAIL {} -- got {!r}, want {!r}".format(desc, got, want))
            fails += 1
    print("  {}/{} case(s) passed".format(len(CASES) - fails, len(CASES)))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
