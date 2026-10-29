"""Offline checks for the shipped media; no LLM calls or server required."""

import json
import math
import shutil
import sqlite3
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "docs" / "assets"
WORK = Path(__file__).parent / "work"


def probe(filename):
    return json.loads(
        subprocess.check_output(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(ASSETS / filename),
            ],
            text=True,
        )
    )


@unittest.skipUnless(shutil.which("ffprobe"), "ffprobe is required for media checks")
class MediaTests(unittest.TestCase):
    def test_mp4_is_full_hd_and_has_no_audio(self):
        data = probe("northwind-demo.mp4")
        self.assertEqual(len(data["streams"]), 1)
        video = data["streams"][0]
        self.assertEqual(video["codec_type"], "video")
        self.assertEqual(video["codec_name"], "h264")
        self.assertEqual(video["pix_fmt"], "yuv420p")
        self.assertEqual((video["width"], video["height"]), (1920, 1080))
        self.assertEqual(video["r_frame_rate"], "30/1")
        self.assertTrue(20 <= float(data["format"]["duration"]) <= 35)

    def test_gif_is_short_and_small(self):
        data = probe("demo.gif")
        video = data["streams"][0]
        self.assertEqual(video["codec_name"], "gif")
        self.assertEqual((video["width"], video["height"]), (1200, 675))
        self.assertTrue(9 <= float(data["format"]["duration"]) <= 11)
        self.assertLess(int(data["format"]["size"]), 10 * 1024 * 1024)
        # No NETSCAPE application extension: do not loop indefinitely.
        self.assertNotIn(b"NETSCAPE2.0", (ASSETS / "demo.gif").read_bytes())

    def test_poster_is_full_hd(self):
        video = probe("demo-poster.png")["streams"][0]
        self.assertEqual((video["width"], video["height"]), (1920, 1080))

    @unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg is required for decoding")
    def test_media_decodes_without_errors(self):
        for name in ("northwind-demo.mp4", "demo.gif"):
            with self.subTest(name=name):
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-xerror",
                        "-i",
                        str(ASSETS / name),
                        "-f",
                        "null",
                        "-",
                    ],
                    check=True,
                    capture_output=True,
                )


class SourceDataTests(unittest.TestCase):
    @unittest.skipUnless(
        (WORK / "turn.json").exists(), "capture evidence is local-only"
    )
    def test_captured_results_match_read_only_database(self):
        turn = json.loads((WORK / "turn.json").read_text())
        events = turn["events"]
        self.assertFalse(any(e["type"] == "error" for e in events))
        sql = next(e["sql"] for e in events if e["type"] == "sql")
        table = next(e for e in events if e["type"] == "table")
        database = ROOT / "data" / "northwind.sqlite"
        with sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True) as connection:
            connection.execute("PRAGMA query_only=ON")
            cursor = connection.execute(sql)
            self.assertEqual([col[0] for col in cursor.description], table["columns"])
            rows = cursor.fetchall()
        self.assertEqual(len(rows), 5)
        self.assertEqual(len(rows), len(table["rows"]))
        for actual, recorded in zip(rows, table["rows"]):
            for value, expected in zip(actual, recorded):
                if isinstance(value, float):
                    self.assertTrue(math.isclose(value, expected, abs_tol=0.0001))
                else:
                    self.assertEqual(value, expected)


if __name__ == "__main__":
    unittest.main()
