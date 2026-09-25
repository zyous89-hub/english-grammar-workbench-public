"""Experimental routing of aligned OCR crops, never destructive ink removal.

Pixels and raw OCR remain evidence. Reference overlap is not a handwriting
label or font classifier; mixed crops need a separate response/mark review.
Thresholds below are development heuristics, not calibrated probabilities.
"""
import cv2
import numpy as np


def reference_evidence(student, reference):
    """Inputs must share scale and coordinates, without artificial padding."""
    if student.ndim != 2 or student.shape != reference.shape or not student.size:
        raise ValueError("aligned grayscale crops of equal nonempty shape required")
    kernel = np.ones((15, 15), np.uint8)
    background = cv2.morphologyEx(student, cv2.MORPH_CLOSE, kernel)
    ref_background = cv2.morphologyEx(reference, cv2.MORPH_CLOSE, kernel)
    ink = background.astype(np.int16) - student.astype(np.int16) > 25
    printed = ref_background.astype(np.int16) - reference.astype(np.int16) > 25
    # 3px tolerance at the OCR input scale; retain uncertain overlaps as mixed.
    printed = cv2.dilate(printed.astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    residual = ink & ~printed
    count, _, stats, _ = cv2.connectedComponentsWithStats(residual.astype(np.uint8))
    largest = int(stats[1:, cv2.CC_STAT_AREA].max()) if count > 1 else 0
    total = int(ink.sum())
    overlap = int((ink & printed).sum())
    return {
        "ink_pixels": total, "print_overlap_pixels": overlap,
        "print_overlap_fraction": overlap / total if total else 0.0,
        "residual_pixels": int(residual.sum()), "largest_residual": largest,
        "content_pixels": int(student.size),
        "parameters": {"local_background_kernel": 15, "contrast": 25,
                       "print_tolerance_px": 3, "residual_component_limit": 12,
                       "mixed_overlap_fraction": 0.2},
    }, residual


def route_candidate(evidence, *, shaded, alignment_ok, stage="shade"):
    """Only route; caller preserves image, OCR, and recognition provenance.

    Print-only stage isolates overlap from the later shaded-residual gate.
    Unknown alignment never authorizes automatic selection or exclusion.
    """
    if stage not in ("print", "shade"):
        raise ValueError("stage must be print or shade")
    if not alignment_ok:
        return "alignment_review"
    overlap = evidence["print_overlap_fraction"]
    small = evidence["largest_residual"] <= 12
    if stage == "shade" and shaded and small:
        return "reference_print_background" if overlap >= 0.2 else "mixed_shade_background"
    if overlap >= 0.2:
        return "reference_print" if small else "mixed_print_review"
    return "student_candidate"


def eligible_answer(text, score, route):
    """No answer-key correction and no slicing noisy strings into digits."""
    import re
    if route != "student_candidate" or score < 0.8:
        return None
    if not re.fullmatch(r"[\s①②③④⑤1-5,，().]+", text):
        return None
    digits = sorted(set("①②③④⑤".index(c) + 1 if c in "①②③④⑤" else int(c)
                        for c in text if c in "①②③④⑤12345"))
    return digits or None
