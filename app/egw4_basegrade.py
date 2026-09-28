"""Local I/O adapter for frozen rules; no transcription input or OCR execution."""
import argparse
from collections import Counter
import copy
import hashlib
import json
import os
from pathlib import Path

import cv2
import numpy as np

from tools.classify_grid_stages import (
    REASONS, classify, overlaps, question_review, required_answer_count, student_choices,
)
from tools.compare_f08_circles import connected_circles, duplicate, exemptions
from tools.export_result import export
from tools.scan_resolution import inspect_scan_sizes


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def link(path, output):
    return os.path.relpath(Path(path).resolve(), output.resolve()).replace('\\', '/')


def classify_assigned(assigned, source, output):
    """Same region projection and base review as build(), without evaluation labels."""
    raw = read(assigned/'results.json')
    evaluation = read(assigned/'evaluation.json')
    source_questions = {q['id']: q for q in read(source/'questions.json')}
    ids = {q['id'] for q in evaluation}
    if len(ids) != len(evaluation) or not ids <= source_questions.keys():
        raise ValueError('Question IDs must be unique and belong to the selected source')
    if any(r['question_id'] not in ids for r in raw):
        raise ValueError('Assigned crop outside the selected question scope')
    pages = {p['page']: p for p in inspect_scan_sizes(read(source/'pages.json'), source)}
    regions = []
    for r in raw:
        stage, reason = classify(r)
        ev = r['reference_evidence']
        regions.append(dict(id=r['id'], question=r['question_id'], stage=stage,
            reason=reason, text=r['text'], score=r['score'], route=r['route'],
            input=link(r['input'], output), source=link(r['source_input'], output),
            ocr_executed=r['ocr_executed'], empty=r['empty'],
            box=r['box'], preserved_choices=r['preserved_choices'],
            choice=student_choices(r['text']) if stage == 0 else None,
            semantic_annotation=r.get('semantic_annotation'),
            reread_conflict=r.get('reread_conflict'),
            ownership_review=r.get('ownership_review', False),
            circle_search=({**r['circle_search'], 'input': link(r['circle_search']['input'], output)}
                if (r.get('circle_search') or {}).get('input') else r.get('circle_search')),
            retry_search=({**r['retry_search'], 'input': link(r['retry_search']['input'], output)}
                if (r.get('retry_search') or {}).get('input') else r.get('retry_search')),
            mixed_print=(not r['preserved_choices'] and not r['answer_excluded']
                and ev['print_overlap_fraction'] >= .2 and ev['largest_residual'] > 12),
            reference_evidence=ev, exclusion_evidence=r['exclusion_evidence']))
    if len({r['id'] for r in regions}) != len(regions):
        raise ValueError('Duplicate assigned crop IDs')
    questions = []
    for q in evaluation:
        if q['page'] != source_questions[q['id']]['page']:
            raise ValueError('Question page differs from its source')
        count = required_answer_count(source_questions[q['id']]['source_text'])
        selected = [r for r in regions if r['question'] == q['id']]
        review = question_review(selected, q['key_answer'], pages.get(q['page']), expected_count=count)
        questions.append(dict(id=q['id'], page=q['page'], required_count=count,
            context=link(q['context'], output), review=review,
            assigned_crops=[r['id'] for r in selected],
            comparison=dict(status='전사 미확인', transcription_verified=False)))
    provenance_path = assigned/'provenance.json'
    provenance = read(provenance_path) if provenance_path.exists() else {}
    payload = dict(runs=[dict(id=assigned.name, order=1, questions=questions, regions=regions)],
        reasons=REASONS, pages=sorted({q['page'] for q in questions}),
        source_note='독립 검증 · 확정 전사 없음 · 자동확정은 판독 정확성 검증 완료를 뜻하지 않습니다.',
        recognition_provenance=provenance)
    return payload, pages


def compare_policies(classified, pages, output):
    """Same connected-arcs/F08 calls as run(); no compare_label or accuracy metrics."""
    run = classified['runs'][0]
    regions = run['regions']
    evidence = {}
    image_hashes = {}
    for q in run['questions']:
        assigned = [r for r in regions if r['question'] == q['id']]
        candidates = [r for r in assigned if r['stage'] == 0]
        for r in assigned:
            if r['reason'] not in ('6', '7') or not any(overlaps(r['box'], c['box']) for c in candidates):
                continue
            path = (output/r['input']).resolve()
            raw = path.read_bytes()
            image_hashes[str(path)] = hashlib.sha256(raw).hexdigest()
            image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
            if image is None or min(image.shape) <= 20:
                raise ValueError(f'Invalid crop: {path}')
            gray = image[10:-10, 10:-10]
            detected = connected_circles(gray)
            evidence[r['id']] = dict(circles=detected,
                duplicates=[c['id'] for c in candidates if duplicate(r, c, gray, detected)])
    policies = {}
    for mode in ('broad', 'duplicate'):
        rows = []
        for q in run['questions']:
            assigned = [r for r in regions if r['question'] == q['id']]
            allowed = exemptions(assigned, evidence, mode)
            answer = ','.join(map(str, q['review']['key'])) if q['review']['key'] else ''
            review = question_review(assigned, answer, pages[q['page']],
                f08_exemptions=allowed, expected_count=q.get('required_count'))
            rows.append(dict(id=q['id'], page=q['page'], review=review,
                required_count=q.get('required_count'),
                comparison=dict(status='전사 미확인', transcription_verified=False),
                exemptions=allowed, changed=review != q['review'],
                context=link(output/q['context'], output/'comparison')))
        reasons = Counter(code for q in rows for code in {r['code'] for r in q['review']['reasons']})
        summary = dict(questions=len(rows),
            automatic=sum(q['review']['selection'] is not None for q in rows),
            held=sum(q['review']['selection'] is None for q in rows),
            hold_reason_counts=dict(reasons),
            top_hold_reasons=[dict(code=code, message=REASONS[code], questions=count)
                              for code, count in reasons.most_common(5)],
            transcription_status='전사 미확인',
            source_note=classified['source_note'], circle_detector='connected-arcs',
            pages=classified['pages'], regions=len(regions),
            grading=dict(Counter(q['review']['status'] for q in rows)))
        policies[mode] = dict(summary=summary, rows=rows)
    return policies, dict(detector=evidence, source_sha256=image_hashes)


def export_classification(classified, output):
    """Remove only duplicated peel display entries from a separate export copy."""
    display = copy.deepcopy(classified)
    removed = []
    for region in display['runs'][0]['regions']:
        for key in ('circle_search', 'retry_search'):
            trace = region.get(key)
            while trace:
                if trace.get('method') == 'enclosure' and trace.get('reads'):
                    assert len(trace['reads']) == 1, 'Peel must contain exactly one recorded read'
                    reading = trace['reads'][0]
                    assert (output/trace['input']).resolve() == (output/reading['input']).resolve()
                    assert all(trace[k] == reading[k] for k in ('text', 'score', 'input_sha256'))
                    # The exporter already emits trace.input/text/score as direct retry evidence.
                    removed.append(dict(crop_id=region['id'], input=reading['input']))
                    del trace['reads']
                trace = trace.get('previous_retry')
    return display, removed


def grade(assigned, source, output, assessment_id, rules_version, title='독립 검증 · 전사 미확인'):
    if output.exists():
        raise ValueError('Use a fresh output directory; previous results are preserved')
    inputs = [assigned/'results.json', assigned/'evaluation.json', source/'questions.json', source/'pages.json']
    hashes = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in inputs}
    classified, pages = classify_assigned(assigned, source, output)
    policies, evidence = compare_policies(classified, pages, output)
    output.mkdir(parents=True)
    (output/'comparison').mkdir()
    save(output/'classification.json', classified)
    display, removed = export_classification(classified, output)
    save(output/'classification-export.json', display)
    for mode, data in policies.items():
        comparison = output/'comparison'/f'{mode}.json'
        save(comparison, data)
        export(comparison, output/'classification-export.json', output/'result'/mode,
               assessment_id, rules_version, title)
    hashes.update(evidence['source_sha256'])
    for path, digest in hashes.items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != digest:
            raise ValueError(f'Input changed while grading: {path}')
    save(output/'comparison/evidence.json', evidence)
    save(output/'summary.json', dict(policies={m: d['summary'] for m, d in policies.items()},
        rules_version=rules_version, input_sha256=hashes, transcription_status='전사 미확인',
        export_display_only=dict(redundant_peel_read_entries=removed, grading_data_unchanged=True)))
    return {m: d['summary'] for m, d in policies.items()}


def run(source, assigned, output, *, commit, student):
    return grade(assigned, source, output, f'independent167-{student}', commit,
                 f'{student} · 독립 검증 · 전사 미확인')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('assigned', 'source', 'output'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--assessment-id', required=True)
    parser.add_argument('--rules-version', required=True)
    parser.add_argument('--title', default='독립 검증 · 전사 미확인')
    args = parser.parse_args()
    print(json.dumps(grade(args.assigned, args.source, args.output, args.assessment_id,
                           args.rules_version, args.title), ensure_ascii=False, indent=2))
