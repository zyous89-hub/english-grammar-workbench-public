"""Teacher-only choice-mark evidence, applied after frozen grading results."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import shutil
import uuid

import cv2
import numpy as np

from src.result_files import image_path, load_result, write_result
from tools.classify_grid_stages import student_choices
from tools.page_first_ocr import read, save, sha

# Exact mark_ref.py thresholds in existing 300dpi context pixels.
PARAMETERS = dict(coordinate_scale='aligned_300dpi_context', dark=150, match_threshold=.72,
                  nms=18, core_size=32, box_padding=4, left_strip=12,
                  left_extra_bottom=8, print_kernel=5, minimum_ink=40,
                  cancel_half_height=8, cancel_search=480, cancel_width=200)


def load_templates(folder):
    templates = {}
    for label in range(1, 6):
        image = cv2.imdecode(np.fromfile(folder/f'{label}.png', np.uint8), 0)
        if image is None or image.shape != (40, 40):
            raise ValueError('Five 40x40 grayscale choice templates required')
        templates[label] = image
    return templates


def detect(student, templates):
    candidates = []
    if min(student.shape) < 32:
        return []
    for label, template in templates.items():
        scores = cv2.matchTemplate(student, template[4:-4, 4:-4], cv2.TM_CCOEFF_NORMED)
        ys, xs = np.where(scores >= .72)
        candidates += [(float(scores[y, x]), label, int(x), int(y)) for y, x in zip(ys, xs)]
    candidates.sort(reverse=True)
    kept = []
    for score, label, x, y in candidates:
        if all(abs(x-kx) > 18 or abs(y-ky) > 18 for _, kx, ky in kept):
            kept.append((label, x, y))
    return kept


def measure(student, templates):
    """Same pixels, matching, windows and integer run lengths as mark_ref.py."""
    if student.ndim != 2 or not student.size:
        raise ValueError('Nonempty grayscale context required')
    marks = []
    for label, x, y in detect(student, templates):
        x0, y0 = x-4, y-4
        if x0-12 < 0 or y0-4 < 0 or y0+44 > student.shape[0] or x0+40 > student.shape[1]:
            continue
        glyph = cv2.dilate(np.uint8(templates[label] < 150), np.ones((5, 5), np.uint8))
        window = student[y0:y0+40, x0:x0+40]
        inner = int(((window < 150) & (glyph == 0)).sum())
        left = int((student[y0+4:y0+44, x0-12:x0] < 150).sum())
        band = student[y+8:y+24, x+36:min(student.shape[1], x+36+480)] < 150
        span = run = 0
        for present in band.any(axis=0):
            run = run+1 if present else 0
            span = max(span, run)
        marks.append(dict(symbol='①②③④⑤'[label-1], box=[x,y,x+32,y+32],
                          measure_box=[x0-12,y0,x0+40,y0+44],
                          cancel_box=[x+36,y+8,min(student.shape[1],x+36+480),y+24],
                          window_pixels=inner, left_strip_pixels=left, ink_pixels=inner+left,
                          horizontal_span=span, cancelled=span >= 200,
                          marked=inner+left >= 40 and span < 200))
    return marks


def recommend(question, marks):
    """Five unique labels first; evidence only on held, single-answer questions."""
    key = student_choices(question['answer_key'] or '')
    if question['judgement'] != '보류' or key is None or len(key) != 1:
        return None
    if sorted(m['symbol'] for m in marks) != list('①②③④⑤'):
        return None
    marked = [m for m in marks if m['marked'] and not m['cancelled']]
    return marked[0] if len(marked) == 1 else None


def inspect(result_path, templates_path, output):
    """Use existing context evidence without alignment, resizing, keys or OCR."""
    if output.exists():
        raise FileExistsError(output)
    result = load_result(result_path)
    templates = load_templates(templates_path)
    tracked = {str(p.resolve()):sha(p) for p in [result_path, *[templates_path/f'{i}.png' for i in range(1,6)]]}
    output.mkdir(parents=True); (output/'evidence').mkdir()
    results = {}; contexts = {}
    for q in result['questions']:
        evidence = [e for e in q['evidence_images'] if e['id'] == 'context']
        if len(evidence) != 1:
            raise ValueError('Exactly one context image required per question')
        path = image_path(result_path.parent, evidence[0]['path'])
        tracked[str(path)] = sha(path)
        student = cv2.imdecode(np.fromfile(path, np.uint8), 0)
        if student is None:
            raise ValueError(f'Unreadable context: {q["id"]}')
        marks = measure(student, templates)
        contexts[q['id']] = dict(path=str(path), sha256=tracked[str(path)], size=list(student.shape[::-1]))
        for item in marks:
            l,t,r,b = item['measure_box']
            h,w = student.shape
            bounds = [max(0,l-24),max(0,t-24),min(w,r+48),min(h,b+24)]
            l,t,r,b = bounds
            # Content-derived names avoid using external question IDs as file paths.
            image = student[t:b,l:r]
            ok, encoded = cv2.imencode('.png', image)
            if not ok:
                raise OSError('Cannot encode recommendation evidence')
            raw = encoded.tobytes(); digest = hashlib.sha256(raw).hexdigest()
            dest = output/'evidence'/f'{digest}.png'
            dest.write_bytes(raw)
            item.update(image=dest.relative_to(output).as_posix(), image_sha256=digest, image_box=bounds)
        results[q['id']] = marks
    for path, digest in tracked.items():
        if sha(Path(path)) != digest:
            raise ValueError(f'Source changed: {path}')
    data = dict(parameters=PARAMETERS, questions=results, contexts=contexts, source_hashes=tracked)
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
    for name in ('result', 'templates', 'output'):
        p.add_argument(name, type=Path)
    p = sub.add_parser('attach')
    for name in ('result', 'measurements', 'output'):
        p.add_argument(name, type=Path)
    args = parser.parse_args()
    if args.action == 'inspect':
        data = inspect(args.result, args.templates, args.output)
        print(f"Measured {len(data['questions'])} questions; no grading changes")
    else:
        items = attach(args.result, args.measurements, args.output)
        print(f'Added {len(items)} teacher-only recommendations')
