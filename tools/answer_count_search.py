"""One bounded reread inside existing question crops; no key/label-guided selection."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

from tools.classify_grid_stages import classify, required_answer_count, student_choices


def needs_search(rows, count, alignment):
    if count is None or not alignment or not alignment.get('matrix'):
        return False
    if alignment['inliers'] <= 30 or not math.isfinite(alignment['median_error']) or alignment['median_error'] > 3:
        return False
    if any(r.get('semantic_annotation') or r.get('count_search') for r in rows):
        return False
    choices = {tuple(student_choices(r['text'])) for r in rows if classify(r)[0] == 0}
    return len(choices) <= 1 and max(map(len, choices), default=0) < count


def reread_image(gray):
    """Only remove white outer margin, then enlarge 2x; retain all source ink."""
    ys, xs = np.where(gray < 255)
    if not len(xs):
        return None
    tight = gray[ys.min():ys.max()+1, xs.min():xs.max()+1]
    large = cv2.resize(tight, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
    return cv2.copyMakeBorder(large, 10, 10, 10, 10, cv2.BORDER_CONSTANT, value=255)


def reconcile(original, extra):
    """No score maximization or count-based answer selection; conflicts stop."""
    result = dict(original)
    old_valid, new_valid = classify(original)[0] == 0, classify(extra)[0] == 0
    result['count_search'] = dict(attempts=1, text=extra['text'], score=extra['score'],
                                  input=extra['input'], input_sha256=extra['input_sha256'],
                                  previous_text=original['text'], previous_score=original['score'])
    if old_valid and new_valid and student_choices(original['text']) != student_choices(extra['text']):
        result['reread_conflict'] = [student_choices(original['text']), student_choices(extra['text'])]
    elif not old_valid and new_valid:
        # Keep original crop/box for geometry and mark detection; only the reread text is adopted.
        result.update(text=extra['text'], score=extra['score'])
    return result


def run(batch, source, output, model):
    if output.exists():
        raise ValueError('Use a new output directory; never overwrite a prior run')
    hashes = {}
    def read(path):
        raw = path.read_bytes(); hashes[str(path.resolve())] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    def save(path, value):
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    rows = read(batch/'results.json')
    if any(r.get('count_search') for r in rows):
        raise ValueError('This batch already had its one count-search pass')
    questions = read(source/'questions.json')
    pages = {p['page']:p for p in read(source/'pages.json')}
    assert len({r['id'] for r in rows}) == len(rows)
    assert {r['question_id'] for r in rows} <= {q['id'] for q in questions}
    counts = {q['id']:required_answer_count(q['source_text']) for q in questions}
    output.mkdir(parents=True)
    inputs = output/'inputs'; inputs.mkdir()
    prepared, selected = [], []
    for q in questions:
        assigned = [r for r in rows if r['question_id'] == q['id']]
        if not needs_search(assigned, counts[q['id']], pages.get(q['page'])):
            continue
        selected.append(q['id'])
        for r in assigned:
            if r['empty'] or r['answer_excluded'] or r['route'] != 'student_candidate':
                continue
            x0,y0,x1,y1 = r['box']; a,b,c,d = q['zone']
            assert a <= x0 < x1 <= c and b <= y0 < y1 <= d, r['id']
            path = Path(r['input']); raw = path.read_bytes()
            assert hashlib.sha256(raw).hexdigest() == r['input_sha256'], r['id']
            transformed = reread_image(cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE))
            if transformed is None:
                continue
            dest = inputs/(r['id']+'.png')
            assert cv2.imwrite(str(dest), transformed)
            prepared.append({**r, 'input':str(dest.resolve()),
                             'input_sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
    save(inputs/'regions.json', prepared)
    save(output/'plan.json', dict(required_counts=counts, questions=selected, crops=len(prepared),
         max_extra_passes=1, transform='all-ink bounding box, nearest 2x, white padding 10', source_hashes=hashes))
    print(json.dumps(dict(search_questions=len(selected), crops=len(prepared)), ensure_ascii=False), flush=True)
    if prepared:
        subprocess.run([sys.executable, '-m', 'tools.run_added_ink_ocr', str(inputs), str(source),
                        str(output/'extra-ocr'), str(model)], check=True)
        extra = {r['id']:r for r in read(output/'extra-ocr/results.json')}
        assert set(extra) == {r['id'] for r in prepared}
        assert all(r['ocr_executed'] for r in extra.values())
    else:
        extra = {}
    combined = [reconcile(r, extra[r['id']]) if r['id'] in extra else r for r in rows]
    shared = output/'shared-batch'; shared.mkdir()
    save(shared/'results.json', combined)
    (shared/'evaluation.json').write_bytes((batch/'evaluation.json').read_bytes())
    save(shared/'provenance.json', dict(
        note=f'130의 공통 OCR 결과에서 지시문 개수가 부족한 {len(selected)}문항의 일반 필기 {len(extra)}조각만 1회 추가 인식했습니다. 같은 추가 결과로 두 안을 비교하며 F12 개수 불일치 보류를 적용합니다. 선택 표시·1단계 제외 조각은 재인식하지 않고, 서로 다른 숫자 조각을 합치지 않습니다.',
        method='132 bounded count search, explicit instruction only; F12 enabled; no key/label-guided selection',
        fresh_result_sha256=hashlib.sha256((shared/'results.json').read_bytes()).hexdigest(),
        parent_result_sha256=hashes[str((batch/'results.json').resolve())], additional_ocr=len(extra),
        required_counts=counts, source_hashes=hashes))
    for path, digest in hashes.items():
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest, path
    print(json.dumps(dict(additional_ocr=len(extra), recovered=sum(classify(a)[0]!=0 and classify(b)[0]==0 for a,b in zip(rows,combined)),
                         reread_conflicts=sum(bool(r.get('reread_conflict')) for r in combined)), ensure_ascii=False))


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    for name in ('batch','source','output','model'):
        p.add_argument(name,type=Path)
    a=p.parse_args(); run(a.batch,a.source,a.output,a.model)
