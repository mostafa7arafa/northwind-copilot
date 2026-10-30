"""Exercise the launcher's Uvicorn boundary with a real loopback socket."""

from __future__ import annotations

import json
import os
import re
import shlex
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest


def test_launcher_rejects_forwarded_remote_peer(tmp_path):
    root = Path(__file__).resolve().parents[1]
    script = (root / "dev.sh").read_text()
    match = re.search(r"uv run --no-sync uvicorn (.*?) &", script, re.DOTALL)
    assert match is not None
    args = shlex.split(match.group(1).replace("\\\n", " "))
    assert "--no-proxy-headers" in args
    assert args[args.index("--host") + 1] == "127.0.0.1"
    # Use the actual launcher command, without a reloader, on an isolated port.
    args.remove("--reload")
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    args[args.index("--port") + 1] = str(port)
    env = {
        **os.environ,
        "WORKSPACE_DATABASE_URL": f"sqlite+aiosqlite:///{tmp_path}/workspace.sqlite",
        "DATASET_DATA_DIR": str(tmp_path / "datasets"),
        "SENTRY_DSN": "",
        "LANGSMITH_API_KEY": "",
        "LANGCHAIN_TRACING_V2": "false",
        "LANGSMITH_TRACING": "false",
        "OPENAI_API_KEY": "",
        "OPENROUTER_API_KEY": "",
    }
    with (tmp_path / "server.log").open("w+") as log:
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", *args],
            cwd=root,
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        try:
            base = f"http://127.0.0.1:{port}"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            for _ in range(200):
                try:
                    with opener.open(base + "/api/health", timeout=0.5) as response:
                        assert response.status == 200
                    break
                except urllib.error.URLError:
                    assert proc.poll() is None, "Uvicorn exited before startup"
                    time.sleep(0.1)
            else:
                raise AssertionError("Uvicorn did not become ready")
            request = urllib.request.Request(
                base + "/api/datasets",
                headers={
                    "X-Forwarded-For": "203.0.113.1",
                    "X-Forwarded-Host": "untrusted.example",
                    "X-Forwarded-Proto": "https",
                },
            )
            # A local proxy must not conceal a forwarded remote client.
            with pytest.raises(urllib.error.HTTPError) as exc:
                opener.open(request, timeout=5)
            assert exc.value.code == 403
            local_request = urllib.request.Request(
                base + "/api/datasets", headers={"X-Forwarded-For": "127.0.0.1"}
            )
            with opener.open(local_request, timeout=5) as response:
                assert response.status == 200
                assert json.load(response) == []
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
