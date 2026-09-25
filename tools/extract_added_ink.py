"""Create actual OCR inputs containing only estimated added ink.

Unlike review routing, this whitens reference-overlapping pixels, including
student ink at those positions. Originals are retained. Exact separation at
overlapping strokes is impossible; these masks are development estimates.
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from tools.ocr_reference_filter import reference_evidence


def extract_added_ink(student, reference):
    evidence, residual = reference_evidence(student, reference)
    extracted = np.full_like(student, 255)
    extracted[residual] = student[residual]
    return extracted, evidence


def prepare(batch, output):
    load = lambda name: json.loads((batch / name).read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in load("questions.json")}
    pages = {p["id"]: p for p in load("pages.json")}
    # Fresh extraction must not require previous OCR results.
    rows = load("regions.json")
    output.mkdir(parents=True, exist_ok=False)
    (output / "crops").mkdir()
    originals, manifest = {}, []
    for row in rows:
        q = questions[row["question_id"]]
        page_id = f'{q["set"]}-{q["page"]:02}'
        page = pages[page_id]
        if page["inliers"] <= 30 or page["median_error"] > 3:
            raise ValueError(f"Alignment requires review: {page_id}")
        reference_path = batch / "pages" / f"{page_id}-original.png"
        if page_id not in originals:
            originals[page_id] = cv2.imread(str(reference_path), 0)
        source = Path(row["input"])
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        if row.get("input_sha256") and source_hash != row["input_sha256"]:
            raise ValueError(f"Source changed: {row['id']}")
        student = cv2.imread(str(source), 0)[10:-10, 10:-10]
        l, t, r, b = row["box"]
        reference = cv2.resize(originals[page_id][t:b, l:r],
                               (student.shape[1], student.shape[0]))
        extracted, evidence = extract_added_ink(student, reference)
        dest = output / "crops" / f'{row["id"]}.png'
        padded = cv2.copyMakeBorder(extracted, 10, 10, 10, 10,
                                    cv2.BORDER_CONSTANT, value=255)
        if not cv2.imwrite(str(dest), padded):
            raise OSError(f"Cannot write {dest}")
        manifest.append({"id": row["id"], "question_id": row["question_id"],
                         "input": str(dest), "input_sha256": hashlib.sha256(dest.read_bytes()).hexdigest(),
                         "source_input": str(source), "source_input_sha256": source_hash,
                         "reference_page": str(reference_path), "box": row["box"],
                         "reference_evidence": evidence, "empty": not bool(np.any(extracted < 255)),
                         "mode": "added-ink-only; reference overlap whitened"})
    (output / "regions.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"crops": len(manifest), "empty": sum(r["empty"] for r in manifest),
                      "new_ocr_calls": 0, "originals_preserved": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.batch, args.output)
