"""Teacher-only choice-mark evidence, applied after frozen grading results."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import shutil
import uuid

import cv2
import numpy as np

from src.result_files import image_path, load_result, write_result
from tools.classify_grid_stages import student_choices
from tools.extract_added_ink import choice_boxes
from tools.page_first_ocr import associate, read, save, sha

# Fixed in reference-page pixels, before native-resolution OCR crop scaling.
PARAMETERS = dict(box_padding=4, left_strip=12, print_padding=2,
                  minimum_ink=40, cancel_width=200, cancel_gap=4,
                  adaptive_block=31, adaptive_offset=14, reference_dark=195)


def added_ink(student, reference):
    if student.ndim != 2 or student.shape != reference.shape or not student.size:
        raise ValueError('Aligned grayscale pages of equal nonempty shape required')
    ink = cv2.adaptiveThreshold(student, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                               cv2.THRESH_BINARY_INV, 31, 14)
    printed = cv2.dilate(np.uint8(reference < 195), np.ones((5, 5), np.uint8))
    return np.uint8((ink > 0) & (printed == 0))


def measure(ink, choice, zone):
    """Count near-label ink; reject a connected horizontal span in that row."""
    x, y, right, bottom = choice['box']
    a, b, c, d = map(int, zone)
    h, w = ink.shape
    left, top = max(a, 0, math.floor(x)-16), max(b, 0, math.floor(y)-4)
    end, base = min(c, w, math.ceil(right)+4), min(d, h, math.ceil(bottom)+4)
    if not 0 <= left < end <= w or not 0 <= top < base <= h:
        raise ValueError('Choice box outside question/page')
    pixels = int(np.count_nonzero(ink[top:base, left:end]))
    # ponytail: horizontal gaps up to 4px only; no semantic cancellation classifier.
    strip = cv2.morphologyEx(ink[top:base, a:c], cv2.MORPH_CLOSE, np.ones((1, 5), np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(strip, 8)
    touching = set(np.unique(labels[:, left-a:end-a])) - {0}
    span = max((int(stats[i, cv2.CC_STAT_WIDTH]) for i in touching), default=0)
    cancelled = span >= 200
    return dict(symbol=choice['symbol'], box=choice['box'], measure_box=[left, top, end, base],
                ink_pixels=pixels, horizontal_span=span, cancelled=cancelled,
                marked=pixels >= 40 and not cancelled)


def recommend(question, marks):
    """Never return evidence for an automatic result or a multiple-answer key."""
    key = student_choices(question['answer_key'] or '')
    if question['judgement'] != '보류' or key is None or len(key) != 1:
        return None
    marked = [m for m in marks if m['marked'] and not m['cancelled']]
    return marked[0] if len(marked) == 1 else None


def inspect(source, questions_path, output):
    """Read source pixels/printed locations once; no key, OCR, or transcription."""
    if output.exists():
        raise FileExistsError(output)
    questions = read(questions_path)
    if len({q['id'] for q in questions}) != len(questions):
        raise ValueError('Duplicate question IDs')
    pages = {p['id']:p for p in read(source/'pages.json')}
    choices = choice_boxes(source, pages)
    tracked = {str(p.resolve()):sha(p) for p in [questions_path, source/'pages.json']}
    output.mkdir(parents=True); (output/'evidence').mkdir()
    results = {q['id']:[] for q in questions}
    page_metadata = {}
    for page_id, page in pages.items():
        group = [q for q in questions if q['set'] == page_id.rsplit('-', 1)[0] and q['page'] == page['page']]
        if not group:
            continue
        matrix = np.asarray(page.get('matrix'), dtype=float)
        if (matrix.shape != (3, 3) or not np.isfinite(matrix).all() or page['inliers'] <= 30
                or not math.isfinite(page['median_error']) or page['median_error'] > 3):
            raise ValueError(f'Alignment requires review: {page_id}')
        ref_path = source/'pages'/f'{page_id}-original.png'
        scan_path = source/'sources'/Path(page['source']).name
        pdf_path = source/'sources'/f"{page_id.rsplit('-', 1)[0]}-original.pdf"
        for path in (ref_path, scan_path, pdf_path):
            tracked[str(path.resolve())] = sha(path)
        reference = cv2.imdecode(np.fromfile(ref_path, np.uint8), 0)
        native = cv2.imdecode(np.fromfile(scan_path, np.uint8), 0)
        if reference is None or native is None:
            raise ValueError(f'Unreadable page: {page_id}')
        h, w = reference.shape
        student = cv2.warpPerspective(cv2.resize(native, (w, h)), matrix, (w, h), borderValue=255)
        ink = added_ink(student, reference)
        page_metadata[page_id] = dict(reference_size=[w, h], scan_size=list(native.shape[::-1]))
        for number, choice in enumerate(choices[page_id]):
            if choice['symbol'] not in '①②③④⑤':
                continue
            owner = associate(choice['box'], group)
            if owner['status'] != 'assigned':
                continue
            q = next(q for q in group if q['id'] == owner['candidates'][0]['question_id'])
            if not 0 <= q['zone'][0] < q['zone'][2] <= w or not 0 <= q['zone'][1] < q['zone'][3] <= h:
                raise ValueError('Question zone outside reference page')
            item = measure(ink, choice, q['zone'])
            # Unaltered student pixels around the measured box; include nearby marks.
            l, t, r, b = item['measure_box']
            bounds = [max(0, l-24), max(0, t-24), min(w, r+48), min(h, b+24)]
            l, t, r, b = bounds
            path = output/'evidence'/f'{page_id}-{number:04}.png'
            if not cv2.imwrite(str(path), student[t:b, l:r]):
                raise OSError(f'Cannot write {path}')
            item.update(image=path.relative_to(output).as_posix(), image_box=bounds,
                        image_sha256=sha(path), page_id=page_id)
            results[q['id']].append(item)
    for path, digest in tracked.items():
        if sha(Path(path)) != digest:
            raise ValueError(f'Source changed: {path}')
    data = dict(parameters=PARAMETERS, questions=results, pages=page_metadata, source_hashes=tracked)
    save(output/'measurements.json', data)
    return data


def attach(result_path, measurements_path, output):
    """Add evidence only to a fresh output, preserving every existing question field."""
    original = load_result(result_path)
    measurements = read(measurements_path)
    if measurements['parameters'] != PARAMETERS:
        raise ValueError('Recommendation thresholds differ from the fixed version')
    if not {q['id'] for q in original['questions']} <= measurements['questions'].keys():
        raise ValueError('Missing question measurements')
    if output.exists():
        raise FileExistsError(output)
    output.mkdir(parents=True)
    result = deepcopy(original)
    recommendations = []
    for q in result['questions']:
        for e in q['evidence_images']:
            dest = image_path(output, e['path']); dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(image_path(result_path.parent, e['path']), dest)
        mark = recommend(q, measurements['questions'][q['id']])
        if mark is None:
            continue
        ident = 'choice-mark-recommendation'
        if any(e['id'] == ident for e in q['evidence_images']):
            raise ValueError('Recommendation evidence already exists')
        source = image_path(measurements_path.parent, mark['image'])
        if sha(source) != mark['image_sha256']:
            raise ValueError('Recommendation image changed')
        relative = f"evidence/{mark['image_sha256']}.png"
        image_path(output, relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, image_path(output, relative))
        q['evidence_images'].append(dict(id=ident,
            label=f"추천 {mark['symbol']} · 선택 표시 기반 · 확인 필요", path=relative))
        recommendations.append(dict(id=q['id'], symbol=mark['symbol'], **{'measurement':mark}))
    result['result_id'] = str(uuid.uuid4())
    result['generated_at'] = datetime.now(timezone.utc).isoformat()
    write_result(output/'result.json', result)
    correction = result_path.parent/'teacher-corrections.json'
    if correction.exists():
        shutil.copyfile(correction, output/correction.name)
    save(output/'recommendations.json', dict(parameters=PARAMETERS, recommendations=recommendations,
         parent_result_sha256=sha(result_path), measurements_sha256=sha(measurements_path)))
    return recommendations


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('inspect')
    for name in ('source', 'questions', 'output'):
        p.add_argument(name, type=Path)
    p = sub.add_parser('attach')
    for name in ('result', 'measurements', 'output'):
        p.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.action == 'inspect':
        data = inspect(args.source, args.questions, args.output)
        print(f"Measured {len(data['questions'])} questions; no grading changes")
    else:
        items = attach(args.result, args.measurements, args.output)
        print(f'Added {len(items)} teacher-only recommendations')
