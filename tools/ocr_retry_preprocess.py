"""User-specified Otsu retry transforms (conversation160)."""
import re
import cv2
import numpy as np

SHAPES = "①②③④⑤○◯□■◇△▽@©OoDⓞ◎"


def should_reread(text, score):
    t = (text or "").strip()
    return t == "0" or (score < 0.8 and t != "" and all(ch in SHAPES for ch in t))


def _holes(mask):
    # 조각 바깥에서 배경을 따라가도 닿지 않는 빈 공간 = 닫힌 구멍
    bg = (mask == 0).astype(np.uint8)
    pad = cv2.copyMakeBorder(bg, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=1)
    cv2.floodFill(pad, None, (0, 0), 2)
    return pad[1:-1, 1:-1] == 1


def peel_enclosures(gray, min_area=8):
    # 1·2번: 닫힌 구멍 안에 다른 덩어리를 통째로 품은 덩어리(테두리)를 큰 것부터 반복해서 지움
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    n, lab, st, _ = cv2.connectedComponentsWithStats(ink, connectivity=8)
    keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= min_area]
    peeled = False
    while True:
        for i in sorted(keep, key=lambda k: -st[k, cv2.CC_STAT_AREA]):
            hole = _holes(np.where(lab == i, 255, 0).astype(np.uint8))
            if any(np.all(hole[lab == j]) for j in keep if j != i):
                keep.remove(i)
                peeled = True
                break
        else:
            break
    return np.isin(lab, keep).astype(np.uint8) * 255 if peeled and keep else None


def whole_ink(gray):
    # 3번: 테두리를 지우지 않고 조각 전체 잉크
    _, ink = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return ink


def normalise(content, target_h=40, pad=24):
    # 글씨에 딱 맞게 자르고 높이 40px, 사방 24px 흰 여백, 흰 바탕 검은 글씨
    ys, xs = np.nonzero(content)
    c = content[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    s = target_h / c.shape[0]
    c = cv2.resize(c, (max(1, int(round(c.shape[1] * s))), target_h), interpolation=cv2.INTER_AREA)
    return 255 - cv2.copyMakeBorder(c, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
