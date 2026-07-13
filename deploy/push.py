#!/usr/bin/env python3
"""Деплой на VPS по SSH: синхронизация файлов + docker compose up."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = Path(__file__).resolve().parent / "remote.env"

EXCLUDE_DIRS = {".venv", "venv", ".git", "__pycache__", ".pytest_cache", "data", ".cursor"}
ALWAYS_SKIP_FILES = {"deploy/remote.env"}


def load_remote_env() -> dict[str, str]:
    if not ENV_PATH.exists():
        print(f"Создай {ENV_PATH} из deploy/remote.env.example", file=sys.stderr)
        raise SystemExit(1)

    values: dict[str, str] = {}
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def ssh_base(env: dict[str, str]) -> list[str]:
    cmd = ["ssh", "-p", env.get("VPS_PORT", "22"), "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new"]
    key = env.get("SSH_KEY", "")
    if key:
        cmd.extend(["-i", key])
    cmd.append(f"{env['VPS_USER']}@{env['VPS_HOST']}")
    return cmd


def run(cmd: list[str], *, input_bytes: bytes | None = None) -> None:
    print("$", " ".join(cmd))
    result = subprocess.run(cmd, input=input_bytes, capture_output=bool(input_bytes))
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def should_skip(rel: Path, *, sync_env: bool) -> bool:
    if set(rel.parts) & EXCLUDE_DIRS:
        return True
    rel_posix = rel.as_posix()
    if rel_posix in ALWAYS_SKIP_FILES:
        return True
    if rel_posix == ".env" and not sync_env:
        return True
    if rel.name.endswith((".pyc", ".pyo", ".log", ".db")):
        return True
    return False


def build_archive(env: dict[str, str]) -> Path:
    sync_env = env.get("SYNC_ENV", "1") == "1"
    tmp = tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()

    with tarfile.open(tmp_path, "w:gz") as tar:
        for path in ROOT.rglob("*"):
            rel = path.relative_to(ROOT)
            if should_skip(rel, sync_env=sync_env):
                continue
            if path.is_dir():
                continue
            tar.add(path, arcname=rel.as_posix())

    return tmp_path


def remote_script(app_dir: str, *, bootstrap: bool) -> str:
    lines = [
        "set -e",
        f"mkdir -p {app_dir}",
        f"cd {app_dir}",
        "tar xzf /tmp/stalzone-deploy.tgz",
    ]
    if bootstrap:
        lines.extend(
            [
                "if ! command -v docker >/dev/null; then",
                "  curl -fsSL https://get.docker.com | sh",
                "fi",
                "mkdir -p data",
            ]
        )
    lines.extend(
        [
            "docker compose up -d --build",
            "docker compose ps",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy stalzone-monitor to VPS")
    parser.add_argument("--bootstrap", action="store_true", help="Install Docker on VPS if missing")
    parser.add_argument("--check", action="store_true", help="Only test SSH connection")
    args = parser.parse_args()

    env = load_remote_env()
    for key in ("VPS_HOST", "VPS_USER", "VPS_APP_DIR"):
        if not env.get(key):
            print(f"Заполни {key} в {ENV_PATH}", file=sys.stderr)
            return 1

    app_dir = env["VPS_APP_DIR"]
    ssh = ssh_base(env)

    if args.check:
        run(ssh + ["bash", "-lc", "echo OK: $(hostname) && docker compose version"])
        print("SSH OK")
        return 0

    archive = build_archive(env)
    try:
        scp = ["scp", "-P", env.get("VPS_PORT", "22"), "-o", "BatchMode=yes"]
        if env.get("SSH_KEY"):
            scp.extend(["-i", env["SSH_KEY"]])
        scp.append(str(archive))
        scp.append(f"{env['VPS_USER']}@{env['VPS_HOST']}:/tmp/stalzone-deploy.tgz")
        run(scp)

        script = remote_script(app_dir, bootstrap=args.bootstrap)
        run(ssh + ["bash", "-s"], input_bytes=script.encode("utf-8"))
    finally:
        archive.unlink(missing_ok=True)

    print(f"\nDeployed to {env['VPS_USER']}@{env['VPS_HOST']}:{app_dir}")
    print(f"Logs: ssh ... 'cd {app_dir} && docker compose logs -f'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
