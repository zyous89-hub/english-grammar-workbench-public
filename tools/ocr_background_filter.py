"""Experimental gate for nearly uniform gray-only OCR crops, not general ink removal.

Thresholds are development heuristics in 8-bit grayscale at the existing crop scale.
Return the original pixels unless the entire nonwhite crop passes the gate.
"""
import cv2
import numpy as np


def suppress_flat_background(gray):
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
    info.update(median=median, dark_contrast=contrast, largest_area=largest)
    # Any substantial dark stroke vetoes removal of the entire crop.
    if 150 <= median <= 235 and contrast <= 18 and largest >= 150:
        info['ignored'] = True
        return np.full_like(gray, 255), info
    return gray.copy(), info
