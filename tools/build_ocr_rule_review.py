"""Build the offline review form from the audited rule inventory (no student data)."""
from pathlib import Path
import hashlib
import json
import re
from ocr_rule_readable import RULES, ORIGINS, ANSWERS, entries

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = ROOT / "docs/ocr-rule-inventory-079.md"
    raw = source.read_text(encoding="utf-8")
    rules, category = [], ""
    for line in raw.splitlines():
        if re.match(r"## [A-G]\. ", line):
            category = line[3:]
        match = re.fullmatch(r"\| ([A-G]\d{2}) \| (.*?) \| (.*?) \|", line)
        if match:
            rid, rule, origin = match.groups()
            rules.append(dict(id=rid, category=category, rule=rule, origin=origin))
    assert len(rules) == len({r["id"] for r in rules}) == 72
    readable, origins = entries(RULES), entries(ORIGINS)
    assert set(readable) == set(origins) == {r['id'] for r in rules}
    answers = entries(ANSWERS)
    for rule in rules:
        rule.update(rule=readable[rule['id']], origin=origins[rule['id']],
                    response=answers.get(rule['id'], ''))
    extra = ('이 검토본은 목록 079의 72개 규칙을 읽기 쉬운 문장으로 정리하고, 대화 082의 답변과 변경 상태를 추가했습니다.\n\n'
             'A02: 학생 폴더·원본 PDF·답지 PDF를 직접 지정하는 개발용 경로를 추가했습니다.\n'
             'G01: 새 경로는 지정한 답지의 시작 페이지부터 읽습니다.\n'
             'A01: 새 경로에서는 세트를 직접 지정하지만 기존 페이지 매핑은 남아 있습니다.\n'
             'A06: 두 단 구조는 사용자 수용 사항입니다. 고정 여백은 아직 변경하지 않았습니다.\n\n'
             '최신 추출 입력은 076, 마지막 채점은 075입니다. 새 준비 경로의 실제 전체 배치 실행과 재채점은 하지 않았습니다.\n\n'
             '현재 없는 기능: 필기 연결에 따른 문항 경계 확장, 삭제된 학생 획 복원, 선택·취소 표시 의미 판독, 여러 조각의 복수 답 통합, 지정 폰트 판별, 국소 구김 보정.\n\n'
             'C 객관식 경로에서 사용하지 않는 것: 밑줄 기반 서술형 추출, 일반 행 기반 서술형 추출, 다른 교재 묶음의 전용 설정.\n'
             '과거 혼합 보류 분기, 과거 음영 실험값, 078의 유사 손상 탐색 기준은 현행 채점 규칙이 아닙니다.')
    snapshot = ROOT / 'docs/ocr-rule-inventory-083.json'
    snapshot.write_text(json.dumps(dict(version='083', rules=rules, additional_notes=extra), ensure_ascii=False, indent=2), encoding='utf-8')
    data = dict(version="083", source="docs/ocr-rule-inventory-083.json",
                source_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
                previous_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                rules=rules, additional_notes=extra)
    template = (ROOT / "tools/templates/ocr-rule-review.html").read_text(encoding="utf-8")
    output = template.replace("__RULE_DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
    target = ROOT / "docs/ocr-rule-review.html"
    target.write_text(output, encoding="utf-8")
    (ROOT / 'docs/ocr-rule-review-083.html').write_text(output, encoding='utf-8')
    print(f"Built {len(rules)} rules: {target}")


if __name__ == "__main__":
    build()
