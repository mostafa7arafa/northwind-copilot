"""Export an edited, audio-free MP4, a short GIF and a static poster.

Requires FFmpeg/ffprobe with libx264 and drawtext, plus fontconfig.
Run cards.mjs first. Raw recordings and intermediates stay in ignored work/.
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(os.environ.get("DEMO_WORK_DIR", Path(__file__).parent / "work")).resolve()
OUT = ROOT / "docs" / "assets"


def run(*args):
    subprocess.run([str(arg) for arg in args], check=True)


def encode(inputs, filters, target, duration=None):
    args = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *inputs]
    if duration is not None:
        args += ["-t", str(duration)]
    run(
        *args,
        "-vf",
        filters,
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "18",
        "-pix_fmt",
        "yuv420p",
        "-r",
        "30",
        target,
    )


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    marks = json.loads((WORK / "timing.json").read_text())
    font = subprocess.check_output(
        ["fc-match", "-f", "%{file}", "DejaVu Sans"], text=True
    ).strip()

    # FFmpeg filter filenames are escaped independently of shell arguments.
    def escaped(value):
        return (
            str(value).replace("\\", "\\\\").replace(":", "\\:").replace("'", "'\\''")
        )

    def text(value, x, y, size, color, name):
        file = WORK / f"label-{name}.txt"
        file.write_text(value, encoding="utf-8")
        return (
            f"drawtext=fontfile='{escaped(font)}':textfile='{escaped(file)}':"
            f"x={x}:y={y}:fontsize={size}:fontcolor={color}"
        )

    footer = text(
        "Northwind sample data  |  Real app footage  |  Waiting time trimmed",
        160,
        1030,
        20,
        "0x9eacc4",
        "footer",
    )
    segments = []
    for name, duration in [("intro", 3), ("outro", 3.5)]:
        encode(
            ["-loop", "1", "-i", str(WORK / f"{name}.png")],
            "fps=30,setsar=1",
            WORK / f"{name}.mp4",
            duration,
        )

    scenes = [
        ("question", marks["ready"], marks["submit"], "01 / Ask a business question"),
        (
            "working",
            marks["submit"],
            min(marks["submit"] + 3, marks["results"]),
            "02 / Follow the analysis",
        ),
        (
            "results",
            marks["results"],
            marks["chart"],
            "03 / Inspect the SQL and real results",
        ),
        ("chart", marks["chart"], marks["end"], "04 / See the story in your data"),
    ]
    for name, start, end, label in scenes:
        if end <= start:
            raise ValueError(f"Invalid capture timing for {name}")
        target = WORK / f"{name}.mp4"
        # Spotlight real workspace pixels, rather than shrinking the whole UI.
        if name in {"results", "chart"}:
            headline, detail = (
                (
                    "Readable SQL.\nReal result rows.",
                    "Read-only queries against\nNorthwind sample data.",
                )
                if name == "results"
                else (
                    "From rows\nto insight.",
                    "The top five products\nby revenue in 2017.",
                )
            )
            canvas = (
                "fps=30,crop=760:640:840:110,scale=1064:896:flags=lanczos,"
                "setsar=1,pad=1920:1080:780:110:color=0x080a0f,"
                + text(headline, 120, 300, 58, "0x629aff", f"{name}-headline")
                + ","
                + text(detail, 120, 530, 28, "0xb2bfd2", f"{name}-detail")
            )
        else:
            canvas = "fps=30,setsar=1,pad=1920:1080:160:110:color=0x080a0f"
        filters = (
            canvas + "," + text(label, 160, 40, 32, "0xeef1f8", name) + "," + footer
        )
        encode(
            ["-ss", str(start), "-i", str(WORK / "capture.webm")],
            filters,
            target,
            end - start,
        )
        segments.append(target)
    playlist = WORK / "playlist.txt"
    playlist.write_text(
        "".join(
            f"file '{escaped(file)}'\n"
            for file in [WORK / "intro.mp4", *segments, WORK / "outro.mp4"]
        )
    )
    video = OUT / "northwind-demo.mp4"
    run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        playlist,
        "-an",
        "-c:v",
        "copy",
        "-movflags",
        "+faststart",
        video,
    )

    # A ten-second teaser: question -> SQL/results -> chart, looping forever.
    gif_parts = [
        "[0:v]trim=end=2.5,setpts=PTS-STARTPTS[a]",
        "[1:v]trim=end=2.5,setpts=PTS-STARTPTS[b]",
        "[2:v]trim=start=1.5:end=6.5,setpts=PTS-STARTPTS[c]",
        "[a][b][c]concat=n=3:v=1:a=0,fps=10,scale=1200:-1:flags=lanczos,split[s0][s1]",
        "[s0]palettegen=max_colors=192:stats_mode=diff[p]",
        "[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle[out]",
    ]
    run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-sseof",
        "-2.5",
        "-i",
        WORK / "question.mp4",
        "-i",
        WORK / "results.mp4",
        "-i",
        WORK / "chart.mp4",
        "-filter_complex",
        ";".join(gif_parts),
        "-map",
        "[out]",
        "-an",
        "-loop",
        "0",
        OUT / "demo.gif",
    )
    run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "3",
        "-i",
        WORK / "chart.mp4",
        "-frames:v",
        "1",
        "-update",
        "1",
        OUT / "demo-poster.png",
    )
    metadata = json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(video),
            ],
            text=True,
        )
    )
    assert not any(stream["codec_type"] == "audio" for stream in metadata["streams"])
    print(
        f"Exported {float(metadata['format']['duration']):.1f}s "
        f"silent MP4, GIF and poster to {OUT}"
    )


if __name__ == "__main__":
    main()
