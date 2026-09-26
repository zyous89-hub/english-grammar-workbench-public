"""Read-only, post-run stage audit. Never rerun OCR or change frozen selections."""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path

from tools.ocr_reference_filter import eligible_answer

REASONS = {
    '2': '답 존재 확인 필요 · 추출 후 흰 조각',
    '9': '원본·배경 필터로 제외됨',
    '5': 'OCR 실행 후 인식 결과 없음',
    '6': '신뢰도 부족 · 0.8 미만',
    'score_missing': '점수 미산출 · 기록 확인 필요',
    'not_executed': 'OCR 미실행 · 기록 확인 필요',
    '7': '답 형식 해석 불가 · 기호 의미는 미확인',
    '8': '선택 표시 미해석',
    '11': '확인된 특수 의미 주석',
    'route_unknown': '처리 경로 확인 필요',
    'candidate': '숫자 후보 · 문항 소속과 최종 의미 확인 필요',
}


def classify(r):
    # ponytail: use recorded gates only; no invented handwriting/symbol detector.
    if r['empty']:
        return 1, '2'
    if r['answer_excluded']:
        return 1, '9'
    if not r['ocr_executed']:
        return 2, 'not_executed'
    if not r['text'].strip():
        return 2, '5'
    score = r['score']
    if score is None or not math.isfinite(score):
        return 2, 'score_missing'
    if score < .8:
        return 2, '6'
    if r.get('semantic_annotation'):
        return 3, '11'
    if r['route'] == 'choice_mark_review':
        return 3, '8'
    if r['route'] != 'student_candidate':
        return 3, 'route_unknown'
    if not eligible_answer(r['text'], score, r['route']):
        return 3, '7'
    return 0, 'candidate'


def check():
    r = dict(empty=False, answer_excluded=False, ocr_executed=True,
             text='1,3', score=.8, route='student_candidate')
    assert classify(r) == (0, 'candidate')  # Multiple answers are allowed.
    assert classify(dict(r, empty=True)) == (1, '2')  # Not confirmed no response.
    assert classify(dict(r, answer_excluded=True)) == (1, '9')
    assert classify(dict(r, text='')) == (2, '5')
    assert classify(dict(r, score=None)) == (2, 'score_missing')
    assert classify(dict(r, text='X', score=.2, route='choice_mark_review')) == (2, '6')
    assert classify(dict(r, route='choice_mark_review')) == (3, '8')
    assert classify(dict(r, text='X')) == (3, '7')  # No claim X is a cancellation.
    assert conflict([{'choice':[1]}, {'choice':[3]}])
    assert not conflict([{'choice':[1,3]}, {'choice':[1,3]}])


def conflict(candidates):
    """D-014: distinct valid sets stop at stage 4, never join fragments."""
    return len({tuple(c['choice']) for c in candidates}) > 1


def build(root, output):
    if output.exists():
        raise ValueError('Use a new output directory; existing reports are preserved')
    hashes = {}

    def read(p):
        p = p.resolve()
        b = p.read_bytes()
        hashes[str(p)] = hashlib.sha256(b).hexdigest()
        return json.loads(b)

    def link(p):
        return os.path.relpath(Path(p).resolve(), output.resolve()).replace('\\', '/')

    manifest = read(root/'manifest.json')
    labels = {q['id']: q for q in read(Path(manifest['config']['transcription']))['rows']}
    assert all(q['confirmed_by_user'] for q in labels.values())
    roi_runs = {r['id']: r for r in read(root/'answer-region-review.json')['results']}
    runs = []
    for run in read(root/'results.json'):
        assert run['status'] == 'completed'
        raw = read(root/run['id']/'ocr/results.json')
        regions = []
        for r in raw:
            stage, reason = classify(r)
            regions.append(dict(id=r['id'], question=r['question_id'], stage=stage,
                                reason=reason, text=r['text'], score=r['score'], route=r['route'],
                                input=link(r['input']), source=link(r['source_input']),
                                ocr_executed=r['ocr_executed'], empty=r['empty'],
                                exclusion_evidence=r['exclusion_evidence']))
        by_id = {r['id']: r for r in regions}
        assert len(by_id) == len(regions)
        rois = {q['id']: q for q in roi_runs[run['id']]['rows']}
        transcription = {q['id']: q for q in run['transcription']['rows']}
        questions = []
        for q in run['evaluation']:
            label, roi, previous = labels[q['id']], rois[q['id']], transcription[q['id']]
            near = [by_id[c['id']] for c in roi['crops']]
            stages = sorted({c['stage'] for c in near if c['stage']})
            passed = [c['id'] for c in near if c['stage'] == 0]
            cross = [c['id'] for c in near if c['question'] != q['id']]
            # ROI belongs to a manual diagnostic, not a newly automatic assignment.
            foreign = [c['id'] for c in q['candidates'] if c['id'] not in {x['id'] for x in near}]
            reference = ''
            if label['answer_status'] == 'conflicting_markings':
                reference = '4단계·사유10: 표시 충돌 (사용자 전사 확인, 자동 검출 아님)'
            elif label['answer_status'] == 'do_not_know':
                reference = '3단계·사유11: 모름 표시 (사용자 전사 확인, 자동 검출 아님)'
            elif label['answer_status'] == 'partial_with_question_mark':
                reference = '3단계·사유11 검토: 숫자와 물음표 공존 (전사 확인, 최종 의미 미확정)'
            if reference:
                bucket = '사용자 확인 특수 표시'
            elif conflict(q['candidates']):
                bucket = '4단계 · 사유10 답 후보 충돌'
            elif previous['status'] == '일치':
                bucket = '기존 채택 · 전사 일치'
            elif previous['status'] == '불일치':
                bucket = '기존 채택 · 전사 불일치'
            elif not near:
                bucket = '답 위치의 조각 없음 · 추출 확인'
            elif passed:
                bucket = '답 위치 후보 있음 · 소속/통합 확인'
            elif len(stages) == 1:
                bucket = f'{stages[0]}단계에서 답 위치 조각 전부 중단'
            else:
                bucket = '답 위치 조각이 여러 단계에서 중단'
            questions.append(dict(id=q['id'], page=q['page'], expected=label['transcription'],
                selection=q['selection'], old_status=previous['status'], bucket=bucket,
                stages=stages, reasons=dict(Counter(c['reason'] for c in near)),
                roi_crops=[c['id'] for c in near], passed=passed, cross_assigned=cross,
                candidate_outside_roi=foreign, reference_review=reference,
                multiple_candidate_sets=conflict(q['candidates']), context=link(q['context']),
                label_status=label['answer_status']))
        assert {q['id'] for q in questions} == set(labels)
        runs.append(dict(id=run['id'], order=run['order'], questions=questions, regions=regions,
                         region_counts=dict(Counter(r['reason'] for r in regions)),
                         question_counts=dict(Counter(q['bucket'] for q in questions))))
    all_regions = [r for run in runs for r in run['regions']]
    all_questions = [q for run in runs for q in run['questions']]
    summary = dict(settings=len(runs), unique_questions=len(labels), questions=len(all_questions),
        regions=len(all_regions), region_counts=dict(Counter(r['reason'] for r in all_regions)),
        stage_counts=dict(Counter(r['stage'] for r in all_regions)),
        question_counts=dict(Counter(q['bucket'] for q in all_questions)),
        old_counts=dict(Counter(q['old_status'] for q in all_questions)),
        roi_region_counts=dict(Counter(r for q in all_questions for r,n in q['reasons'].items() for _ in range(n))),
        crossed_question_cases=sum(bool(q['cross_assigned']) for q in all_questions),
        multiple_candidate_set_cases=sum(q['multiple_candidate_sets'] for q in all_questions),
        ocr_already_executed_on_stage1=sum(r['stage']==1 and r['ocr_executed'] for r in all_regions))
    assert len(runs) == 36 and len(all_questions) == 1260 and len(all_regions) == 12969
    assert sum(summary['region_counts'].values()) == len(all_regions)
    for name, digest in hashes.items():
        assert hashlib.sha256(Path(name).read_bytes()).hexdigest() == digest, name
    output.mkdir(parents=True)
    payload = dict(summary=summary, reasons=REASONS, runs=runs,
                   rule_basis=['conversations/2026-09-26-107.md', 'decisions/0013-m1-only-scope.md', 'decisions/0014-b-stage-freeze.md'],
                   method='Recorded first-stop gates; manual answer ROIs and user labels are diagnostic only. No OCR or grading rerun.',
                   source_sha256=hashes)
    (output/'classification.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    template = Path(__file__).with_name('templates')/'stage-classification.html'
    compact = {**payload, 'runs': [{**run, 'regions': [{k:v for k,v in r.items() if k!='exclusion_evidence'} for r in run['regions']]} for run in runs]}
    page=template.read_text(encoding='utf-8').replace('__DATA__',json.dumps(compact,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c'))
    (output/'report.html').write_text(page,encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__ == '__main__':
    check()
    p=argparse.ArgumentParser()
    p.add_argument('root',type=Path)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    build(a.root,a.output)
