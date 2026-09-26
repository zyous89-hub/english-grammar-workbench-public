"""File contract and teacher overlays only. No OCR or grading imports."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import tempfile


JUDGEMENTS = ('정답', '오답', '보류')


class ResultFileError(ValueError):
    pass


def _require(condition, message):
    if not condition:
        raise ResultFileError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _stage(value):
    return value is None or type(value) is int and 1 <= value <= 4


def _answer(value):
    return value is None or isinstance(value, str)


def _timestamp(value):
    try:
        return isinstance(value, str) and datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def image_path(root, relative):
    _require(_text(relative), '근거 이미지 경로가 없습니다.')
    _require(not any(c in relative for c in '\\:*?<>|"\x00') and
             all(p not in ('', '.', '..') and p == p.rstrip(' .') for p in relative.split('/')),
             '근거 이미지는 결과 폴더 안의 상대 경로여야 합니다.')
    path = (root / relative).resolve()
    _require(path.is_relative_to(root.resolve()), '근거 이미지가 결과 폴더 밖을 가리킵니다.')
    _require(path.suffix.lower() in ('.jpg', '.jpeg', '.png'), 'PNG/JPEG 근거 이미지만 지원합니다.')
    return path


def validate_result(data, root):
    _require(isinstance(data, dict) and type(data.get('schema_version')) is int and data['schema_version'] == 1,
             '지원하지 않는 결과 파일 형식입니다.')
    for name in ('assessment_id', 'result_id', 'title'):
        _require(_text(data.get(name)), f'결과의 {name}이 없습니다.')
    _require(_timestamp(data.get('generated_at')), '결과 생성 시각에 시간대가 필요합니다.')
    _require(isinstance(data.get('questions'), list), '문항 목록이 없습니다.')
    ids = set()
    for q in data['questions']:
        _require(isinstance(q, dict), '문항 형식이 잘못됐습니다.')
        for name in ('id', 'label', 'rules_version'):
            _require(_text(q.get(name)), f'문항의 {name}이 없습니다.')
        _require(q['id'] not in ids, '문항 ID가 중복됐습니다.'); ids.add(q['id'])
        _require(q.get('judgement') in JUDGEMENTS, '문항 판정이 잘못됐습니다.')
        for name in ('read_answer', 'answer_key'):
            _require(name in q and _answer(q[name]), f'{name}은 문자열 또는 null이어야 합니다.')
        _require('review_stage' in q and _stage(q['review_stage']), '보류 단계 형식이 잘못됐습니다.')
        _require(isinstance(q.get('reasons'), list), '사유 목록이 없습니다.')
        _require(q['judgement'] != '보류' or bool(q['reasons']), '보류 문항에는 사유가 필요합니다.')
        for reason in q['reasons']:
            _require(isinstance(reason, dict) and _text(reason.get('code')) and _text(reason.get('message'))
                     and 'stage' in reason and _stage(reason['stage']), '사유의 코드·문구·단계를 확인하세요.')
        _require(isinstance(q.get('evidence_images'), list), '근거 이미지 목록이 없습니다.')
        images = set()
        for evidence in q['evidence_images']:
            _require(isinstance(evidence, dict) and _text(evidence.get('id')) and _text(evidence.get('label')),
                     '근거 이미지 ID와 이름표가 필요합니다.')
            _require(evidence['id'] not in images, '근거 이미지 ID가 중복됐습니다.'); images.add(evidence['id'])
            image_path(root, evidence.get('path'))
    return data


def validate_corrections(data, assessment_id):
    _require(isinstance(data, dict) and type(data.get('schema_version')) is int and data['schema_version'] == 1,
             '지원하지 않는 교사 수정 파일 형식입니다.')
    _require(data.get('assessment_id') == assessment_id, '다른 제출의 교사 수정 파일입니다. 적용하지 않았습니다.')
    _require(isinstance(data.get('corrections'), dict), '교사 수정 목록이 잘못됐습니다.')
    for ident, c in data['corrections'].items():
        _require(_text(ident) and isinstance(c, dict), '교사 수정 문항 ID가 잘못됐습니다.')
        _require('read_answer' in c and _answer(c['read_answer']) and c.get('judgement') in JUDGEMENTS,
                 '교사 답과 판정 형식이 잘못됐습니다.')
        _require(isinstance(c.get('note'), str) and _timestamp(c.get('updated_at')),
                 '교사 메모와 수정 시각이 필요합니다.')
        _require(_text(c.get('based_on_result_id')) and _text(c.get('based_on_rules_version')),
                 '교사 수정의 기준 결과·규칙 버전이 필요합니다.')
    return data


def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        _require(key not in obj, f'JSON 키가 중복됐습니다: {key}')
        obj[key] = value
    return obj


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ResultFileError(f'{path.name}을 읽을 수 없습니다. 기존 파일을 보존했습니다.') from error


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.'+path.name, suffix='.tmp', delete=False) as stream:
            temp = Path(stream.name)
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if temp is not None and temp.exists():
            temp.unlink()


def load_result(path):
    return validate_result(read_json(path), path.parent)


def load_state(path):
    result = load_result(path)
    correction_path = path.parent/'teacher-corrections.json'
    if correction_path.exists():
        try:
            raw = correction_path.read_bytes()
            corrections = validate_corrections(json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_unique_object), result['assessment_id'])
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ResultFileError('교사 수정 파일을 읽을 수 없습니다. 기존 파일을 보존했습니다.') from error
        revision = hashlib.sha256(raw).hexdigest()
    else:
        corrections = dict(schema_version=1, assessment_id=result['assessment_id'], corrections={})
        revision = 'missing'
    rows = []
    for q in result['questions']:
        teacher = corrections['corrections'].get(q['id'])
        effective = {k:(teacher or q)[k] for k in ('read_answer', 'judgement')}
        rows.append(dict(automatic=q, teacher=teacher, effective=effective,
                         differs=bool(teacher and any(teacher[k] != q[k] for k in effective))))
    orphaned = sorted(set(corrections['corrections']) - {q['id'] for q in result['questions']})
    return dict(result=result, corrections=corrections, revision=revision, rows=rows, orphaned=orphaned)


def save_correction(path, question_id, read_answer, judgement, note, revision, result_id):
    _require(_answer(read_answer) and judgement in JUDGEMENTS and isinstance(note, str), '수정값 형식을 확인하세요.')
    lock = path.parent/'.teacher-corrections.lock'
    try:
        stream = lock.open('x')
    except FileExistsError as error:
        raise ResultFileError('다른 저장 작업이 진행 중입니다. 잠시 후 다시 시도하세요.') from error
    try:
        stream.close()
        state = load_state(path)
        _require(state['revision'] == revision, '교사 수정 파일이 바뀌었습니다. 다시 불러온 뒤 저장하세요.')
        _require(state['result']['result_id'] == result_id, '새 채점 결과가 도착했습니다. 다시 불러온 뒤 저장하세요.')
        q = next((q for q in state['result']['questions'] if q['id'] == question_id), None)
        _require(q is not None, '현재 결과에 해당 문항이 없습니다. 기존 수정은 보존했습니다.')
        previous = state['corrections']['corrections'].get(question_id, {})
        state['corrections']['corrections'][question_id] = dict(previous,
            read_answer=read_answer.strip() if isinstance(read_answer, str) else None, judgement=judgement,
            note=note, updated_at=datetime.now(timezone.utc).isoformat(),
            based_on_result_id=result_id, based_on_rules_version=q['rules_version'])
        atomic_json(path.parent/'teacher-corrections.json', state['corrections'])
    finally:
        lock.unlink()
    return load_state(path)


def write_result(path, data):
    validate_result(data, path.parent)
    if path.exists():
        old = load_result(path)
        _require(old['assessment_id'] == data['assessment_id'], '다른 제출의 결과를 덮어쓸 수 없습니다.')
        _require(old['result_id'] != data['result_id'], '재채점에는 새 결과 ID가 필요합니다.')
    atomic_json(path, data)
