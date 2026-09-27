"""One local OCR pass on separable handwriting inside circles or rectangles."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

from tools.answer_count_search import has_retry_history, reread_image
from tools.classify_grid_stages import classify, student_choices
from tools.compare_f08_circles import connected_circles, radius
from tools.ocr_attached_enclosure import to_digit


def eligible(row):
    # Existing acceptance remains >= .8. Only already-held low-score rows enter.
    # The enclosing shape is found in pixels, not guessed from the OCR character.
    return (classify(row) == (2, '6') and row['score'] <= .8
            and row['route'] == 'student_candidate' and not row.get('preserved_choices')
            and not row.get('semantic_annotation') and not row.get('reread_conflict')
            and not has_retry_history(row))


def enclosures(gray):
    """Return inner masks and boundary samples; no semantic cancellation detector."""
    yy, xx = np.indices(gray.shape)
    found = []
    for circle in connected_circles(gray):
        distance = radius(xx, yy, circle['ellipse'])
        found.append((distance < .9, (distance >= .9) & (distance <= 1.1),
                      dict(kind='circle', ellipse=circle['ellipse'])))
    contours, _ = cv2.findContours(np.uint8(gray < 195), cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    for contour in contours:
        polygon = cv2.approxPolyDP(contour, .025 * cv2.arcLength(contour, True), True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        points = polygon[:, 0, :].astype(float)
        edges = np.roll(points, -1, axis=0) - points
        lengths = np.linalg.norm(edges, axis=1)
        if lengths.min() < max(20, .3 * min(gray.shape)) or cv2.contourArea(polygon) < .08 * gray.size:
            continue
        # Allow hand-drawn tilted boxes; reject very acute diamond-like corners.
        cosines = np.sum(edges * np.roll(edges, 1, axis=0), axis=1) / (lengths * np.roll(lengths, 1))
        if np.max(np.abs(cosines)) > .55:
            continue
        filled = np.zeros(gray.shape, np.uint8); cv2.fillPoly(filled, [polygon], 1)
        distance = cv2.distanceTransform(filled, cv2.DIST_L2, 3)
        margin = max(2, .05 * lengths.min())
        inside = distance > margin
        boundary = np.zeros(gray.shape, np.uint8)
        cv2.polylines(boundary, [polygon], True, 1, 3)
        found.append((inside, boundary.astype(bool), dict(kind='rectangle', polygon=polygon[:, 0, :].tolist())))
    return found


def inner_image(gray):
    """Remove separate enclosing frames, retaining every enclosed ink component."""
    found = enclosures(gray)
    if not found:
        return None, dict(status='no_enclosure')
    _, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(gray < 195), 8)
    parts = {i:np.where(labels == i) for i in range(1, len(stats)) if stats[i, cv2.CC_STAT_AREA] >= 8}
    frames = []
    for interior, boundary, geometry in found:
        inside, ambiguous = [], False
        for i, (yy, xx) in parts.items():
            contained = interior[yy, xx]
            if contained.any():
                if not contained.all():
                    ambiguous = True
                    break
                inside.append(i)
        if not inside or ambiguous:
            continue  # A bare 0/6/8/9 has no separate ink inside its hole.
        outline = {i for i, (yy, xx) in parts.items() if boundary[yy, xx].any() and i not in inside}
        if len(outline) == 1:
            frames.append((set(inside), next(iter(outline)), geometry))
    removed = {outline for _, outline, _ in frames}
    candidates = {tuple(sorted(inside - removed)) for inside, _, _ in frames if inside - removed}
    if len(candidates) != 1:
        return None, dict(status='unseparated_or_ambiguous', shapes=len(found))
    ids = next(iter(candidates))
    if set(parts) != set(ids) | removed:
        return None, dict(status='outside_ink')  # Never discard an answer outside the selected frame.
    mask = np.isin(labels, ids)
    # Retain antialiasing immediately around the kept components, but reject any
    # contact with other dark ink. No reconstruction/inpainting of missing strokes.
    keep = cv2.dilate(np.uint8(mask), np.ones((3, 3), np.uint8)).astype(bool)
    if np.any(keep & (gray < 195) & ~mask):
        return None, dict(status='touching_ink')
    separated = np.where(keep, gray, 255).astype(np.uint8)
    image = reread_image(separated)
    return image, dict(status='prepared', shapes=[geometry for _, _, geometry in frames], components=len(ids),
                       ink_pixels=int(mask.sum()), transform='whole interior components; nearest 2x; padding 10')


def reconcile(original, extra, evidence, *, allow_low_confidence_consensus=False):
    updated = dict(original)
    trace = dict(evidence, attempts=1, previous_text=original['text'], previous_score=original['score'],
                 text=extra['text'], score=extra['score'], input=extra['input'],
                 input_sha256=extra['input_sha256'], adopted=False)
    if classify(extra)[0] == 0:
        before, after = student_choices(original['text']), student_choices(extra['text'])
        if before is not None and before != after:
            method = evidence.get('method')
            widths = method == 'hull_stable'
            expected = [2.0, 2.5, 3.0] if widths else [16, 24]
            reads = evidence.get('confirmation_reads' if method == 'enclosure' else 'reads', [])
            digit = to_digit(extra['text'])
            score = original['score']
            agreed = (allow_low_confidence_consensus
                      and isinstance(score, (int, float)) and math.isfinite(score) and score < .8
                      and method in ('hull_stable', 'size_stable_C', 'circle_strip_D-1',
                                     'circle_strip_D-2', 'enclosure')
                      and original.get('reread_conflict') in (None, [before, after])
                      and digit is not None and isinstance(reads, list) and len(reads) == len(expected)
                      and all(isinstance(r, dict) for r in reads)
                      and [r.get('k' if widths else 'pad_y') for r in reads] == expected
                      and all(to_digit(r.get('text')) == digit
                              and isinstance(r.get('score'), (int, float))
                              and math.isfinite(r['score']) and r['score'] >= .8 for r in reads))
            if agreed:
                updated.pop('reread_conflict', None)
                updated.update(text=extra['text'], score=extra['score'])
                trace.update(status='adopted', adopted=True, low_confidence_consensus=True)
            else:
                updated['reread_conflict'] = ((original.get('reread_conflict') or [before, after])
                                              if allow_low_confidence_consensus else [before, after])
                trace['status'] = 'answer_conflict'
        else:
            updated.update(text=extra['text'], score=extra['score'])
            trace.update(status='adopted', adopted=True)
    else:
        trace['status'] = 'still_unreadable'
    updated['circle_search'] = trace
    return updated


def run(batch, source, output, model):
    if output.exists():
        raise ValueError('Use a new output directory; existing results are preserved')
    tracked = {}
    def read(path):
        raw = path.read_bytes(); tracked[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    def save(path, data):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = read(batch/'results.json')
    if any(has_retry_history(r) for r in rows):
        raise ValueError('This batch already had its one enclosed-ink search')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate crop IDs')
    page_wide = all('question_id' not in r for r in rows)
    if not page_wide and any('question_id' not in r for r in rows):
        raise ValueError('Mixed page and question crops')
    questions = {} if page_wide else {q['id']:q for q in read(source/'questions.json')}
    page_rows = read(source/'pages.json')
    pages = {p['id'] if page_wide else p['page']:p for p in page_rows}
    page_bounds = {}
    if page_wide:
        # Before ownership, the intact physical crop is bounded by its page only.
        for ident in {r['page_id'] for r in rows}:
            raw = (source/'pages'/f'{ident}-original.png').read_bytes()
            tracked[str((source/'pages'/f'{ident}-original.png').resolve())] = hashlib.sha256(raw).hexdigest()
            image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None:
                raise ValueError(f'Invalid reference page: {ident}')
            page_bounds[ident] = [0, 0, image.shape[1], image.shape[0]]
    output.mkdir(parents=True); inputs = output/'inputs'; inputs.mkdir()
    prepared, trace = [], {}
    for row in rows:
        if not eligible(row):
            continue
        if page_wide:
            page = pages[row['page_id']]; bounds = page_bounds[row['page_id']]
            if page['page'] != row['page']:
                raise ValueError('Crop page does not match source page')
        else:
            q = questions[row['question_id']]; page = pages[q['page']]; bounds = q['zone']
        x, y, X, Y = row['box']; a, b, A, B = bounds
        if (not page.get('matrix') or page['inliers'] <= 30 or not math.isfinite(page['median_error'])
                or page['median_error'] > 3 or not (a <= x < X <= A and b <= y < Y <= B)):
            trace[row['id']] = dict(status='alignment_or_bounds', attempts=0)
            continue
        path = Path(row['input']); raw = path.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest != row['input_sha256']:
            raise ValueError(f"Input changed: {row['id']}")
        tracked[str(path.resolve())] = digest
        gray = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if gray is None:
            raise ValueError(f"Invalid input: {row['id']}")
        image, evidence = inner_image(gray)
        trace[row['id']] = dict(evidence, attempts=0)
        if image is None:
            continue
        dest = inputs/(row['id']+'.png')
        if not cv2.imwrite(str(dest), image):
            raise OSError('Could not write OCR input')
        prepared.append(dict(row, input=str(dest.resolve()), input_sha256=hashlib.sha256(dest.read_bytes()).hexdigest()))
    save(inputs/'regions.json', prepared)
    save(output/'plan.json', dict(eligible=len(trace), extra_inputs=len(prepared), crops=trace, max_passes=1))
    print(json.dumps(dict(eligible=len(trace), extra_inputs=len(prepared))), flush=True)
    if prepared:
        subprocess.run([sys.executable, '-m', 'tools.run_added_ink_ocr', str(inputs), str(source),
                        str(output/'extra-ocr'), str(model)], check=True)
        extra = {r['id']:r for r in read(output/'extra-ocr/results.json')}
        if set(extra) != {r['id'] for r in prepared} or not all(r['ocr_executed'] for r in extra.values()):
            raise ValueError('Additional OCR coverage does not match the plan')
    else:
        extra = {}
    combined = [reconcile(r, extra[r['id']], trace[r['id']]) if r['id'] in extra else
                dict(r, circle_search=trace[r['id']]) if r['id'] in trace else r for r in rows]
    shared = output/'shared-batch'; shared.mkdir()
    save(shared/'results.json', combined)
    if page_wide:
        timing = read(batch/'timing.json')
        save(shared/'timing.json', timing)  # Original page scope; extra OCR timing stays separate.
    else:
        (shared/'evaluation.json').write_bytes((batch/'evaluation.json').read_bytes())
    save(shared/'provenance.json', dict(note=f'140: 낮은 점수 필기 중 동그라미·네모 안에서 분리 가능한 내부 획 {len(extra)}조각만 한 차례 추가 OCR. 기존 결과 보존.',
         method='140 bounded circle/rectangle inner search; no key/transcription-guided choice',
         recognition_scope='page_before_ownership' if page_wide else 'question_crop',
         fresh_result_sha256=hashlib.sha256((shared/'results.json').read_bytes()).hexdigest(),
         parent_result_sha256=tracked[str((batch/'results.json').resolve())], source_hashes=tracked))
    for path, digest in tracked.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Source changed: {path}')
    summary = dict(eligible=len(trace), additional_ocr=len(extra),
                   adopted=sum(r.get('circle_search', {}).get('adopted', False) for r in combined),
                   conflicts=sum(r.get('circle_search', {}).get('status') == 'answer_conflict' for r in combined))
    save(output/'summary.json', summary)
    print(json.dumps(summary), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('batch', 'source', 'output', 'model'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args(); run(args.batch, args.source, args.output, args.model)
