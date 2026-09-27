"""One local OCR pass on separable handwriting inside a detected circle."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import unicodedata

import cv2
import numpy as np

from tools.answer_count_search import reread_image
from tools.classify_grid_stages import classify, student_choices
from tools.compare_f08_circles import connected_circles, radius


def target_text(text):
    if text.strip() in ('0', '０'):
        return True
    return any('CIRCLED' in unicodedata.name(c, '') and c.isnumeric() for c in text)


def eligible(row):
    # Existing acceptance remains >= .8. Only already-held low-score rows enter.
    return (classify(row) == (2, '6') and row['score'] <= .8 and target_text(row['text'])
            and row['route'] == 'student_candidate' and not row.get('preserved_choices')
            and not row.get('semantic_annotation') and not row.get('reread_conflict')
            and not row.get('circle_search'))


def inner_image(gray):
    """Keep whole interior components together; never cut a digit off its ring."""
    found = connected_circles(gray)
    if not found:
        return None, dict(status='no_circle')
    _, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8(gray < 195), 8)
    parts = {i:np.where(labels == i) for i in range(1, len(stats)) if stats[i, cv2.CC_STAT_AREA] >= 8}
    candidates = {}
    for circle in found:
        inside, ambiguous = [], False
        for i, (yy, xx) in parts.items():
            distances = radius(xx, yy, circle['ellipse'])
            if distances.min() < .9:
                if distances.max() >= .9:
                    ambiguous = True
                    break
                inside.append(i)
        # One exterior component may be the circle joined to a box. Extra outside
        # components could be another answer: do not silently drop them.
        if inside and not ambiguous and len(parts) - len(inside) == 1:
            candidates[tuple(inside)] = circle
    if len(candidates) != 1:
        return None, dict(status='unseparated_or_ambiguous', circles=len(found))
    ids, circle = next(iter(candidates.items()))
    mask = np.isin(labels, ids)
    # Retain antialiasing immediately around the kept components, but reject any
    # contact with other dark ink. No reconstruction/inpainting of missing strokes.
    keep = cv2.dilate(np.uint8(mask), np.ones((3, 3), np.uint8)).astype(bool)
    if np.any(keep & (gray < 195) & ~mask):
        return None, dict(status='touching_ink')
    separated = np.where(keep, gray, 255).astype(np.uint8)
    image = reread_image(separated)
    return image, dict(status='prepared', ellipse=circle['ellipse'], components=len(ids),
                       ink_pixels=int(mask.sum()), transform='whole interior components; nearest 2x; padding 10')


def reconcile(original, extra, evidence):
    updated = dict(original)
    trace = dict(evidence, attempts=1, previous_text=original['text'], previous_score=original['score'],
                 text=extra['text'], score=extra['score'], input=extra['input'],
                 input_sha256=extra['input_sha256'], adopted=False)
    if classify(extra)[0] == 0:
        before, after = student_choices(original['text']), student_choices(extra['text'])
        if before is not None and before != after:
            updated['reread_conflict'] = [before, after]
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
    if any(r.get('circle_search') for r in rows):
        raise ValueError('This batch already had its one circle-inner search')
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('Duplicate crop IDs')
    questions = {q['id']:q for q in read(source/'questions.json')}
    pages = {p['page']:p for p in read(source/'pages.json')}
    output.mkdir(parents=True); inputs = output/'inputs'; inputs.mkdir()
    prepared, trace = [], {}
    for row in rows:
        if not eligible(row):
            continue
        q = questions[row['question_id']]; page = pages[q['page']]
        x, y, X, Y = row['box']; a, b, A, B = q['zone']
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
    (shared/'evaluation.json').write_bytes((batch/'evaluation.json').read_bytes())
    save(shared/'provenance.json', dict(note=f'139: 낮은 점수 0·원문자 중 분리 가능한 내부 획 {len(extra)}조각만 한 차례 추가 OCR. 기존 결과 보존.',
         method='139 bounded circle-inner search; no key/transcription-guided choice',
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
