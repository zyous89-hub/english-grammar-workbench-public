"""Standalone audit for Pattern/Part, N) multiple-choice PDF keys; no grading writes."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re


def answer(raw):
    # Only a complete leading answer field; never salvage digits from explanation.
    match = re.match(r'[ \t]*([①②③④⑤1-5](?:\s*[,，]\s*[①②③④⑤1-5])*)', raw)
    if not match:
        return None
    tail = raw[match.end():]
    if tail and not re.match(r'[ \t]*(?::|\r|\n|$)', tail):
        return None
    if tail.lstrip().startswith((',', '，', '①', '②', '③', '④', '⑤')):
        return None
    values = ["①②③④⑤".index(c) + 1 if c in "①②③④⑤" else int(c)
              for c in match[1] if c in '①②③④⑤12345']
    return sorted(values) if len(values) == len(set(values)) else None


def audit(pages, expected, set_id):
    text, spans = '', []
    for page, content in pages:
        spans.append((len(text), len(text) + len(content), page))
        text += content + '\n'
    sections = list(re.finditer(r'Pattern\s+([12])(?:\s+Part\s+(\d+))?', text))
    rows, issues = [], []
    if not sections:
        issues.append('Pattern 제목 없음' if text.strip() else 'PDF 텍스트 없음: 스캔 OCR 필요 여부 확인')
    for i, section in enumerate(sections):
        start = section.end()
        end = sections[i+1].start() if i+1 < len(sections) else len(text)
        heads = list(re.finditer(r'(?<![\d(])(\d+)\)\s*', text[start:end]))
        numbers = [int(h[1]) for h in heads]
        if numbers != list(range(1, len(numbers)+1)):
            issues.append(f'Pattern {section[1]}: 문항 순서·누락·중복 확인 필요')
        for j, head in enumerate(heads):
            stop = heads[j+1].start() if j+1 < len(heads) else end-start
            raw = text[start+head.end():start+stop].strip()
            offset = start + head.start()
            rows.append(dict(id=f'{set_id}-p{section[1]}-s{section[2] or 0}-q{head[1]}',
                             page=next(p for a,b,p in spans if a <= offset < b),
                             raw=raw, answer=answer(raw)))
    counts = Counter(r['id'] for r in rows)
    missing = sorted(set(expected)-counts.keys())
    extra = sorted(counts.keys()-set(expected))
    duplicates = sorted(k for k,v in counts.items() if v > 1)
    invalid = [r['id'] for r in rows if r['answer'] is None]
    return dict(ok=not (issues or missing or extra or duplicates or invalid),
                issues=issues, missing=missing, extra=extra, duplicates=duplicates,
                invalid=invalid, rows=rows)


def check():
    assert answer('①, ③\n : 해설') == [1, 3]
    assert answer('2,5: 해설') == [2, 5]
    for bad in ('', '①, ?', '①, ⑥', '①②', '①,①', '① ②', '①,\n?', '6', '①abc'):
        assert answer(bad) is None, bad
    expected = ['C-p1-s0-q1', 'C-p1-s0-q2']
    assert audit([(20,'Pattern 1\n1) ③\n2) ①,②')], expected, 'C')['ok']
    assert not audit([(20,'Pattern 1\n1) ③\n1) ②')], expected, 'C')['ok']
    assert audit([(20,'')], expected, 'C')['missing'] == expected
    print('PASS: multiple answers, malformed tails, duplicates, missing and empty text')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--pdf', type=Path)
    parser.add_argument('--first-page', type=int)
    parser.add_argument('--question-ids', type=Path, help='JSON list of expected IDs')
    parser.add_argument('--set-id', default='C')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.check:
        check()
        return
    if any(x is None for x in (args.pdf, args.first_page, args.question_ids, args.output)):
        parser.error('PDF, first page, question IDs and new output directory required')
    import pypdfium2 as pdf
    expected = json.loads(args.question_ids.read_text(encoding='utf-8-sig'))
    if not isinstance(expected, list) or not expected or not all(isinstance(x,str) for x in expected):
        parser.error('question IDs must be a nonempty string list')
    if len(expected) != len(set(expected)):
        parser.error('duplicate expected question IDs')
    doc = pdf.PdfDocument(str(args.pdf))
    if not 1 <= args.first_page <= len(doc):
        parser.error('first page outside PDF')
    result = audit([(i+1, doc[i].get_textpage().get_text_range())
                    for i in range(args.first_page-1,len(doc))], expected, args.set_id)
    result.update(source_sha256=hashlib.sha256(args.pdf.read_bytes()).hexdigest(),
                  method='PDF text layer, not OCR', first_page=args.first_page)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines = ['# 답지 추출 검사', '', 'PDF 텍스트층 추출입니다. OCR이나 독립적인 내용 정답 검증이 아닙니다.', '',
             '| 문항 | PDF 쪽 | 추출 정답 |', '|---|---|---|']
    lines += [f'| {r["id"]} | {r["page"]} | {r["answer"]} |' for r in result['rows']]
    lines += ['', '검사 결과: ' + json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False)]
    (args.output/'report.md').write_text('\n'.join(lines),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))


if __name__ == '__main__':
    main()
