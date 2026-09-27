"""D experiment: remove the remaining circle after the accepted peel/B paths."""
import cv2

from tools.ocr_attached_enclosure import hull_strip, to_digit
from tools.ocr_retry_preprocess import normalise, should_reread


def normalise2(mask, pad_y, pad_x):
    # Reuse the established height40/INTER_AREA transform with asymmetric padding.
    return cv2.copyMakeBorder(normalise(mask, pad=0), pad_y, pad_y, pad_x, pad_x,
                             cv2.BORDER_CONSTANT, value=255)


def eligible(row):
    return (row['route'] == 'student_candidate' and not row['empty']
            and not row['answer_excluded']
            and not any(c['symbol'] in '①②③④⑤ⓐⓑⓒⓓⓔⓕⓖⓗⓘⓙⓚⓛⓜⓝⓞⓟⓠⓡⓢⓣⓤⓥⓦⓧⓨⓩ'
                        for c in row['preserved_choices'])
            and should_reread(row['text'], row['score'] if row['score'] is not None else float('inf')))


def _two_sizes(mask, ocr):
    a = ocr(normalise2(mask, 16, 24))
    b = ocr(normalise2(mask, 24, 24))
    da, db = to_digit(a[0]), to_digit(b[0])
    if da is not None and da == db and a[1] >= 0.8 and b[1] >= 0.8:
        return b, [a, b]
    return None


def circle_strip_reading(gray, ocr):
    m1 = hull_strip(gray, 2.5)
    if m1 is None:
        return None
    m2 = hull_strip(255 - m1, 2.5)
    return _two_sizes(m2, ocr) if m2 is not None else None


def peeled_circle_strip_reading(peeled, ocr):
    m = hull_strip(255 - peeled, 2.5)
    return _two_sizes(m, ocr) if m is not None else None
