"""Run the single-user backend with disposable recording preferences/workspace.

Use the repository's virtualenv. Never changes .env or saved user preferences.
Recording data lives in ignored work/; do not publish it.
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("DEMO_WORK_DIR", Path(__file__).parent / "work")).resolve()


def main():
    WORK.mkdir(parents=True, exist_ok=True)
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
            "WORKSPACE_DATABASE_URL": f"sqlite+aiosqlite:///{WORK / 'workspace.sqlite'}",
            "DATASET_DATA_DIR": str(WORK / "datasets"),
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
    print(f"Demo backend on loopback only. Recording workspace: {WORK}", flush=True)
    uvicorn.run(
        "northwind_copilot.web.app:app",
        host="127.0.0.1",
        port=8000,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
