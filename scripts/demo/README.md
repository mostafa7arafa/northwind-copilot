# Silent product demo

Approved brief: English, no voiceover/audio; GitHub README teaser and a LinkedIn-ready MP4.

## Deliverables

- `docs/assets/northwind-demo.mp4`: approximately 28 seconds, 1920×1080, H.264/yuv420p, 30 fps, **no audio stream**. Upload this file natively to LinkedIn; nothing has been published automatically.
- `docs/assets/demo.gif`: approximately 10 seconds, 1200×675, 10 fps. Plays once rather than moving indefinitely. The README uses the static poster by default to avoid autoplay, with links to the video and GIF.
- `docs/assets/demo-poster.png`: static alternative.

The demo records the **actual POC app and a live GPT-4.1 mini turn** against built-in Northwind sample data: “Which 5 products generated the most revenue in 2017?” No agent responses or database results are mocked. Waiting time is trimmed and disclosed on screen; this is not a latency benchmark. It does not demonstrate hosted signup/upload or imply the product is deployed. Dataset selection is unnecessary for the built-in sample.

Tools: Playwright + local FFmpeg. Remotion and extra skills are not needed for this cut. Research: [`docs/research/silent-app-demo.md`](../../docs/research/silent-app-demo.md).

## Reproduce

Prerequisites: repo Python/web dependencies, Node ≥20/npm, FFmpeg/ffprobe (`libx264`, `drawtext`, `palettegen`, `paletteuse`) and fontconfig (`fc-match`). Run commands from the repo root unless noted. Ports 8000 and 3000 must be free. Capture uses the existing OpenAI key from `.env` and incurs normal provider usage; no priority tier is requested.

```bash
npm ci --prefix scripts/demo
cd scripts/demo && npx playwright install chromium
cd ../..

# Terminal 1: isolated auth/preferences, no LangSmith tracing, loopback only.
PYTHONIOENCODING=utf-8 .venv/bin/python scripts/demo/serve.py

# Terminal 2: actual frontend, POC mode, loopback only.
cd frontend
NEXT_PUBLIC_HOSTED_MODE=false NEXT_TELEMETRY_DISABLED=1 npm run dev -- --hostname 127.0.0.1

# Terminal 3: one live query, then local exports.
cd scripts/demo
DEMO_TOKEN_FILE=work/auth-token npm run capture
npm run render
```

The screenshot cards use the app's existing octopus icon and installed system fonts. SQL/results and chart scenes crop and enlarge the real workspace for readability; no values are replaced or fabricated. `DEMO_WORK_DIR` optionally redirects work files (use the same absolute path for every command); `DEMO_URL` changes the capture origin. Only recording-specific browser CSS hides Next's dev indicator. Application source, existing preferences and `.env` are not edited.

`work/` and `node_modules/` are ignored. Never commit tokens, auth state, raw videos, traces, or user datasets. Recording uses an ephemeral browser context; authorization is attached only to the app API origin, not Monaco's CDN. The app still calls the cloud LLM and Monaco CDN; local recording is **not offline inference**. Stop both development servers with Ctrl+C after capture.

## Validate before sharing

```bash
python -m unittest discover -s scripts/demo -v
# No audio entry; H.264, 1920×1080 and yuv420p expected.
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,pix_fmt -show_entries format=duration,size -of json docs/assets/northwind-demo.mp4
# GIF dimensions/duration and successful decoding.
ffprobe -v error -show_entries stream=width,height -show_entries format=duration,size -of json docs/assets/demo.gif
ffmpeg -v error -i docs/assets/northwind-demo.mp4 -f null -
```

Replay the entire MP4; inspect the SQL, table, chart, labels and final GitHub URL. Compare `work/turn.json`'s SQL/results with a read-only query against `data/northwind.sqlite`. Inspect at typical README/mobile sizes, and recheck current LinkedIn upload requirements before publishing. README rendering and LinkedIn upload must ultimately be checked on those services; local encoding does not prove acceptance.
