"""Fresh local recognition of added-ink inputs; no recognition cache reuse."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import unicodedata


def run(inputs, source, output, model_dir):
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
    os.environ["HF_HUB_OFFLINE"] = "1"

    def audit(event, args):
        if event in ("socket.connect", "socket.getaddrinfo"):
            raise RuntimeError("OCR network connection blocked")

    sys.addaudithook(audit)
    import cv2
    import numpy as np
    from paddleocr import TextRecognition
    from paddlex.inference.models.text_recognition.processors import CTCLabelDecode
    from tools.ocr_background_filter import suppress_flat_background, suppress_shaded_low_ink
    from tools.ocr_reference_filter import route_candidate

    original_decode = CTCLabelDecode.__call__

    def constrained(self, pred, return_word_box=False, **kwargs):
        x = np.array(pred[0], copy=True)
        ids = [i for i, c in enumerate(self.character) if any(
            "CJK UNIFIED IDEOGRAPH" in unicodedata.name(t, "") or
            "CJK COMPATIBILITY IDEOGRAPH" in unicodedata.name(t, "") or t == "〇" for t in c)]
        x[..., ids] = -np.inf
        return original_decode(self, [x], return_word_box=return_word_box, **kwargs)

    CTCLabelDecode.__call__ = constrained
    rows = json.loads((inputs / "regions.json").read_text(encoding="utf-8"))
    assert len({r["id"] for r in rows}) == len(rows)
    output.mkdir(parents=True, exist_ok=False)
    start = time.perf_counter()
    model = TextRecognition(model_name="PP-OCRv5_server_rec", model_dir=str(model_dir),
                            device="cpu", enable_mkldnn=False)
    results = []
    with (output / "raw-results.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            image = Path(row["input"])
            if hashlib.sha256(image.read_bytes()).hexdigest() != row["input_sha256"]:
                raise ValueError(f"New OCR input changed: {row['id']}")
            source_image = Path(row["source_input"])
            if hashlib.sha256(source_image.read_bytes()).hexdigest() != row["source_input_sha256"]:
                raise ValueError(f"Source changed: {row['id']}")
            a = cv2.imread(str(source_image), 0)
            _, flat = suppress_flat_background(a)
            _, shade = suppress_shaded_low_ink(a)
            ref_route = route_candidate(row["reference_evidence"], shaded=shade["shaded_background"],
                                        alignment_ok=True)
            excluded = flat["ignored"] or shade["ignored"] or row["empty"] or ref_route in (
                "reference_print", "reference_print_background", "mixed_shade_background")
            protected_choice = row.get("requires_choice_mark_review", False)
            if protected_choice:
                excluded = False  # Keep choice/mark evidence for its separate review path.
            # E02: stage-1 exclusions retain their images/evidence without an OCR call.
            executed = not row["empty"] and not excluded
            text, score = "", None
            if executed:
                answer = list(model.predict([str(image)], batch_size=1))[0]
                text, score = answer["rec_text"], float(answer["rec_score"])
            result = {**row, "text": text, "score": score, "ocr_executed": executed,
                      "ignored": not executed, "answer_excluded": bool(excluded),
                      "route": "choice_mark_review" if protected_choice else "excluded_after_extraction" if excluded else "student_candidate",
                      "exclusion_evidence": {"flat": flat, "shade": shade, "reference_route": ref_route},
                      "recognition_origin": "fresh OCR on reference-overlap-removed image",
                      "semantic_annotation": None}
            results.append(result)
            stream.write(json.dumps(result, ensure_ascii=False) + "\n")
            stream.flush()
            if len(results) % 50 == 0:
                print(json.dumps({"done": len(results), "total": len(rows),
                                  "seconds": round(time.perf_counter() - start)}), flush=True)
    for name, value in [("results.json", results), ("timing.json", {
            "seconds": time.perf_counter() - start, "regions": len(rows),
            "ocr_executed": sum(r["ocr_executed"] for r in results),
            "stage1_skipped": sum(not r["ocr_executed"] for r in results),
            "answer_excluded": sum(r["answer_excluded"] for r in results),
            "source": str(source), "inputs": str(inputs), "cached_ocr_reused": 0,
            "network_scope": "Python socket connect and DNS audit hook; not OS-wide proof"})]:
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    print("OCR complete", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("inputs", "source", "output", "model_dir"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    run(args.inputs, args.source, args.output, args.model_dir)
