"""Experimental gate for nearly uniform gray-only OCR crops, not general ink removal.

Thresholds are development heuristics in 8-bit grayscale at the existing crop scale.
Return the original pixels unless the entire nonwhite crop passes the gate.
"""
import cv2
import numpy as np


def suppress_flat_background(gray, max_dark_fraction=0.0):
    """Optional experimental ink allowance; fraction uses the full padded crop."""
    if not 0 <= max_dark_fraction <= 1:
        raise ValueError('max_dark_fraction must be between 0 and 1')
    smooth = cv2.GaussianBlur(gray, (3, 3), 0)
    area = smooth < 245  # Exclude the crop's white padding.
    values = smooth[area]
    info = {"ignored": False, "area_pixels": int(area.sum())}
    if len(values) < 150 or area.mean() < 0.12:
        return gray.copy(), info
    median = float(np.median(values))
    contrast = median - float(values.min())
    count, labels, stats, _ = cv2.connectedComponentsWithStats(area.astype('uint8'))
    largest = int(stats[1:, cv2.CC_STAT_AREA].max()) if count > 1 else 0
    dark_pixels = int(np.count_nonzero(smooth < median - 18))
    dark_fraction = dark_pixels / gray.size
    info.update(median=median, dark_contrast=contrast, largest_area=largest,
                dark_pixels=dark_pixels, total_pixels=int(gray.size),
                dark_fraction=dark_fraction)
    # Default retains the original strict veto; optional allowance is a trial.
    if 150 <= median <= 235 and dark_fraction <= max_dark_fraction and largest >= 150:
        info['ignored'] = True
        return np.full_like(gray, 255), info
    return gray.copy(), info
