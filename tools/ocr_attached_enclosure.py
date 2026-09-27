"""User-specified three-width attached-frame retry (conversation161)."""
import cv2
import numpy as np
from tools.ocr_retry_preprocess import peel_enclosures, normalise


def _clean(mask, min_area=8):
    n, lab, st, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= min_area]
    return np.isin(lab, keep).astype(np.uint8) * 255 if keep else None


def stroke_width(mask):
    cs, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    per = sum(cv2.arcLength(c, True) for c in cs)
    return 2.0 * (mask > 0).sum() / per if per else 0.0


def hull_strip(gray, k):
    # 가장 큰 덩어리의 볼록 껍질 가장자리에서 (k × 획 두께) 안쪽까지의 잉크를 지우고,
    # 그 뒤 동그라미가 숫자를 따로 품게 되면 peel_enclosures로 한 번 더 걷어냄
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    ink = _clean(ink)
    if ink is None:
        return None
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    i = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    comp = np.where(lab == i, 255, 0).astype(np.uint8)
    hull = cv2.convexHull(cv2.findNonZero(comp))
    hmask = np.zeros_like(ink)
    cv2.fillConvexPoly(hmask, hull, 255)
    dist = cv2.distanceTransform(hmask, cv2.DIST_L2, 5)
    out = np.where((hmask > 0) & (dist > k * stroke_width(comp)) & (ink > 0), 255, 0).astype(np.uint8)
    out = _clean(out)
    if out is None:
        return None
    p = peel_enclosures(255 - out)
    return p if p is not None else out


CIRCLED = dict(zip("①②③④⑤", "12345"))


def to_digit(text):
    t = (text or "").strip()
    return CIRCLED.get(t, t) if len(t) == 1 and t in "12345①②③④⑤" else None


def stable_reading(gray, ocr):
    # ocr(image) -> (text, score). 세 폭(2.0/2.5/3.0) 모두 같은 숫자·0.8 이상일 때만 인정. 결과는 2.5의 판독
    reads = []
    for k in (2.0, 2.5, 3.0):
        m = hull_strip(gray, k)
        if m is None:
            return None
        reads.append(ocr(normalise(m)))
    digits = {to_digit(t) for t, s in reads}
    if len(digits) == 1 and None not in digits and all(s >= 0.8 for t, s in reads):
        return reads[1], reads
    return None
