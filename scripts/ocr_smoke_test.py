"""Synthetic printed-JPG OCR smoke test; not a handwriting benchmark.
Run from repository root: python scripts/ocr_smoke_test.py
Requires Pillow, Tesseract on PATH, and Windows Arial.
"""
import hashlib
import json
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, __version__ as pillow_version

out = Path("docs/verification/ocr-smoke-2026-09-23")
out.mkdir(parents=True, exist_ok=True)
expected = [
    "He gose home.",
    "She walk to school.",
    "They walks to school.",
    "He has finished his homework.",
    "He had finished his homework.",
    "The boy playing soccer is my brother.",
    "I am interesting in music.",
    "I am interested in music.",
]
font_path = Path("C:/Windows/Fonts/arial.ttf")
font = ImageFont.truetype(str(font_path), 42)
img = Image.new("RGB", (1400, 760), "white")
draw = ImageDraw.Draw(img)
for i, line in enumerate(expected):
    draw.text((70, 45 + i * 85), line, font=font, fill="black")
image_path = out / "synthetic-printed-answers.jpg"
img.save(image_path, quality=90, dpi=(300, 300))
(out / "expected.txt").write_text("\n".join(expected) + "\n", encoding="utf-8")
exe = shutil.which("tesseract")
if not exe:
    raise SystemExit("Tesseract not found")
command = [exe, str(image_path), "stdout", "-l", "eng", "--psm", "6"]
started_at = datetime.now().astimezone().isoformat()
start = time.perf_counter()
result = subprocess.run(command, capture_output=True, encoding="utf-8", check=True)
elapsed = time.perf_counter() - start
(out / "recognized.txt").write_text(result.stdout, encoding="utf-8")
(out / "stderr.txt").write_text(result.stderr, encoding="utf-8")
# Only blank lines / edge whitespace ignored; spelling and punctuation preserved.
actual = [line.strip() for line in result.stdout.splitlines() if line.strip()]
rows = [{"expected": line, "recognized": actual[i] if i < len(actual) else None,
         "exact_match": i < len(actual) and line == actual[i]}
        for i, line in enumerate(expected)]
model_path = Path(exe).parent / "tessdata/eng.traineddata"
sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
report = {
    "kind": "synthetic_printed_jpg_smoke_test_not_handwriting",
    "started_at": started_at,
    "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    "script_sha256": sha(Path(__file__)),
    "tesseract_version": subprocess.check_output([exe, "--version"], text=True).splitlines()[0],
    "pillow_version": pillow_version,
    "font_sha256": sha(font_path), "image_sha256": sha(image_path),
    "model_sha256": sha(model_path), "command": command,
    "ocr_process_seconds_including_startup": elapsed,
    "expected_lines": len(expected), "recognized_lines": len(actual),
    "exact_match_lines": sum(row["exact_match"] for row in rows),
    "extra_lines": actual[len(expected):], "rows": rows,
    "network": "Local process invoked; no network isolation or traffic audit performed.",
}
(out / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report, ensure_ascii=False, indent=2))
