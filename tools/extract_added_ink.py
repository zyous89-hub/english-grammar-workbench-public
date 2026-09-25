"""Create OCR inputs with added ink and protected printed circled 1..5/a..z.

Unlike review routing, this whitens reference-overlapping pixels, including
student ink at those positions, except protected choice-label boxes. Originals are retained. Exact separation at
overlapping strokes is impossible; these masks are development estimates.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np

from tools.ocr_reference_filter import reference_evidence

PRESERVED_CHOICE_SYMBOLS = frozenset("①②③④⑤" + "".join(chr(c) for c in range(0x24D0, 0x24EA)))


def extract_added_ink(student, reference, preserve_mask=None):
    evidence, residual = reference_evidence(student, reference)
    extracted = np.full_like(student, 255)
    extracted[residual] = student[residual]
    if preserve_mask is not None:
        if preserve_mask.shape != student.shape or preserve_mask.dtype != bool:
            raise ValueError("preserve_mask must be a boolean mask matching the crop")
        extracted[preserve_mask] = student[preserve_mask]
        evidence["preserved_pixels"] = int(preserve_mask.sum())
    return extracted, evidence


def choice_boxes(batch, pages):
    """Read circled 1..5/a..z from the local original PDF, never from the answer key."""
    import pypdfium2 as pdf
    result = {}
    for page_id, info in pages.items():
        set_id = page_id.rsplit("-", 1)[0]
        doc = pdf.PdfDocument(str(batch / "sources" / f"{set_id}-original.pdf"))
        page = doc[info["page"] - 1]
        width, height = page.get_size()
        rendered = cv2.imread(str(batch / "pages" / f"{page_id}-original.png"), 0)
        h, w = rendered.shape
        text = page.get_textpage()
        boxes = []
        for i in range(text.count_chars()):
            char = text.get_text_range(i, 1)
            if char in PRESERVED_CHOICE_SYMBOLS:
                left, bottom, right, top = text.get_charbox(i)
                boxes.append({"symbol": char, "box": [left / width * w, (height-top) / height * h,
                                                      right / width * w, (height-bottom) / height * h]})
        result[page_id] = boxes
        text.close()
        page.close()
        doc.close()
    return result


def choice_preservation_mask(shape, crop_box, choices):
    """Restore only supported circled-label rectangles (+3 pixels for alignment)."""
    h, w = shape
    l, t, r, b = crop_box
    sx, sy = w / (r-l), h / (b-t)
    mask = np.zeros(shape, dtype=bool)
    selected = []
    for choice in choices:
        if choice["symbol"] not in PRESERVED_CHOICE_SYMBOLS:
            continue
        a, c, d, e = choice["box"]
        x1, y1 = max(0, math.floor((a-l)*sx)-3), max(0, math.floor((c-t)*sy)-3)
        x2, y2 = min(w, math.ceil((d-l)*sx)+3), min(h, math.ceil((e-t)*sy)+3)
        if x2 > x1 and y2 > y1:
            mask[y1:y2, x1:x2] = True
            selected.append({**choice, "crop_box": [x1, y1, x2, y2]})
    return mask, selected


def prepare(batch, output):
    load = lambda name: json.loads((batch / name).read_text(encoding="utf-8"))
    questions = {q["id"]: q for q in load("questions.json")}
    pages = {p["id"]: p for p in load("pages.json")}
    choices = choice_boxes(batch, pages)
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
        preserve, selected = choice_preservation_mask(student.shape, row["box"], choices[page_id])
        extracted, evidence = extract_added_ink(student, reference, preserve)
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
                         "preserved_choices": selected,
                         "requires_choice_mark_review": bool(selected),
                         "mode": "added ink plus protected circled 1..5/a..z; selection meaning requires review"})
    (output / "choice-preservation.json").write_text(json.dumps(choices, ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "regions.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"crops": len(manifest), "empty": sum(r["empty"] for r in manifest),
                      "new_ocr_calls": 0, "originals_preserved": True}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("batch", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    prepare(args.batch, args.output)
