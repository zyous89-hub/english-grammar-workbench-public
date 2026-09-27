"""Engine-side adapter. The review UI never imports this module or its rules."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

from src.result_files import ResultFileError, load_result, write_result
from tools.classify_grid_stages import REASONS


def export(comparison, classification, output, assessment_id, rules_version, title='객관식 채점 결과'):
    destination = output/'result.json'
    if destination.exists() and load_result(destination)['assessment_id'] != assessment_id:
        raise ResultFileError('다른 제출의 결과 폴더입니다.')
    data = json.loads(comparison.read_text(encoding='utf-8'))
    classified = json.loads(classification.read_text(encoding='utf-8'))
    assert len(classified['runs']) == 1
    run = classified['runs'][0]
    regions = {r['id']:r for r in run['regions']}
    assert len(regions) == len(run['regions'])
    assert {q['id'] for q in data['rows']} == {q['id'] for q in run['questions']}
    images = output/'evidence'; images.mkdir(parents=True, exist_ok=True)
    def evidence(path, ident, label):
        if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
            raise ResultFileError('지원하지 않는 근거 이미지입니다.')
        raw = path.read_bytes(); digest = hashlib.sha256(raw).hexdigest()
        dest = images/(digest+path.suffix.lower())
        if dest.exists():
            assert hashlib.sha256(dest.read_bytes()).hexdigest() == digest
        else:
            dest.write_bytes(raw)
        return dict(id=ident, label=label, path=dest.relative_to(output).as_posix())
    answer = lambda values: ','.join(map(str, values)) if values is not None else None
    questions = []
    for q in data['rows']:
        review = q['review']; reasons = []
        for r in review['reasons']:
            message = r.get('message') or REASONS.get(r['code'])
            if not message:
                raise ResultFileError(f"엔진이 사유 문구를 제공하지 않았습니다: {r['code']}")
            reasons.append(dict(code=r['code'], message=message, stage=r['stage']))
        proof = [evidence((comparison.parent/q['context']).resolve(), 'context', '학생 원래 문항')]
        ids = sorted(set(review['candidates']) | {i for r in review['reasons'] for i in r['crop_ids']})
        for ident in ids:
            r = regions[ident]
            assert r['question'] == q['id']
            inner = r.get('circle_search') or {}
            shown_score = inner.get('previous_score', r['score'])
            shown_text = inner.get('previous_text', r['text'])
            score = '미실행' if shown_score is None else f"점수 {shown_score:.3f}"
            proof.append(evidence((classification.parent/r['input']).resolve(), ident,
                                  f"OCR 조각 {ident} · 읽은 내용 {shown_text or '없음'} · {score}"))
            if inner.get('input'):
                proof.append(evidence((classification.parent/inner['input']).resolve(), ident+'-inner',
                    f"도형 내부 재인식 {ident} · 읽은 내용 {inner['text'] or '없음'} · 점수 {inner['score']:.3f} · "
                    + ('후보 채택' if inner.get('adopted') else '보류 유지')))
        questions.append(dict(id=q['id'], label=f"{q['page']}쪽 · {q['id']}",
             judgement=review['status'], read_answer=answer(review['proposed_selection']),
             answer_key=answer(review['key']), review_stage=review['stage'] or None,
             reasons=reasons, evidence_images=proof, rules_version=rules_version))
    result = dict(schema_version=1, assessment_id=assessment_id, result_id=str(uuid.uuid4()),
                  generated_at=datetime.now(timezone.utc).isoformat(), title=title, questions=questions)
    write_result(destination, result)
    return dict(path=str(destination.resolve()), questions=len(questions),
                evidence_files=len(list(images.iterdir())), result_id=result['result_id'])


if __name__ == '__main__':
    p=argparse.ArgumentParser()
    for name in ('comparison','classification','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--assessment-id',required=True)
    p.add_argument('--rules-version',required=True)
    p.add_argument('--title',default='객관식 채점 결과')
    a=p.parse_args()
    print(json.dumps(export(a.comparison,a.classification,a.output,a.assessment_id,a.rules_version,a.title),ensure_ascii=False))
