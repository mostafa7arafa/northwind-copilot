"""Run the existing POC backend with disposable recording-only preferences/auth.

Use the repository's virtualenv. Never changes .env or saved user preferences.
The generated token file and settings live in ignored work/; do not publish it.
"""

import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("DEMO_WORK_DIR", Path(__file__).parent / "work")).resolve()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    token_path = WORK / "auth-token"
    token = secrets.token_urlsafe(32)
    # Restrict permissions when opening, not after writing the token.
    fd = os.open(token_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(token)
    preferences = WORK / "preferences.json"
    preferences.write_text(
        json.dumps(
            {
                "preferences": (
                    "Use concise, professional English. "
                    "No profanity or exaggerated claims. "
                    "Do not assume a currency unless the data specifies it."
                )
            }
        )
    )
    os.environ.update(
        {
            "APP_AUTH_TOKEN": token,
            "HOSTED_MODE": "false",
            "LANGSMITH_API_KEY": "",
            "LANGCHAIN_API_KEY": "",
            "LANGSMITH_TRACING": "false",
            "LANGCHAIN_TRACING_V2": "false",
        }
    )
    sys.path.insert(0, str(ROOT))
    # Capture-only process configuration; the application files remain unchanged.
    import uvicorn

    import northwind_copilot.web.preferences as stored_preferences

    stored_preferences._STORE = preferences
    os.chdir(ROOT)
    print(f"Demo backend on loopback only. Token file: {token_path}", flush=True)
    uvicorn.run("northwind_copilot.web.app:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
