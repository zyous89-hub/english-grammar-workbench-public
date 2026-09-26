"""Separate trials for numbered answer sheets; layouts must be selected explicitly."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path
import re
from tools.audit_answer_key import answer, audit


def extract(pages, layout, footer=''):
    rows = []
    pattern = r'(?<!\d)(\d+)\s*번\s*-\s*' if layout == 'explained' else r'(?<![\d(])(\d+)\)\s*'
    for page, text in pages:
        if footer:
            text = text.replace(footer, '')
        heads = list(re.finditer(pattern, text))
        for i, h in enumerate(heads):
            raw = text[h.end():heads[i+1].start() if i+1<len(heads) else len(text)].strip()
            if layout == 'explained':
                m = re.match(r'([①②③④⑤](?:\s*[,，]\s*[①②③④⑤])*)(?=\s|$)', raw)
                value = answer(m[1]) if m and not raw[m.end():].lstrip().startswith((',', '，', '→')) else None
                kind = 'numeric' if value else 'review'
                display = m[1] if value else raw
            else:
                # Whole field, not just the first numeral: correction answers remain text.
                compact = re.sub(r'\s+', ' ', raw).strip()
                value = answer(compact)
                kind = 'numeric' if value else 'text_review'
                display = compact
            rows.append(dict(question=int(h[1]), page=page, kind=kind,
                             answer=value, display=display, raw=raw))
    counts = Counter(r['question'] for r in rows)
    numbers = [r['question'] for r in rows]
    return dict(rows=rows, sequential=bool(numbers) and numbers==list(range(1,len(rows)+1)),
                duplicates=[q for q,n in counts.items() if n>1],
                counts=dict(Counter(r['kind'] for r in rows)))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--check',action='store_true')
    p.add_argument('--pdf',type=Path)
    p.add_argument('--layout',choices=['explained','compact'])
    p.add_argument('--footer',default='')
    p.add_argument('--output',type=Path)
    a=p.parse_args()
    if a.check:
        r=extract([(1,'1) 5\n2) ① accidentally → deliberately\n3) Before proceeding.')],'compact')
        assert [x['kind'] for x in r['rows']]==['numeric','text_review','text_review']
        assert extract([(1,'1 번 - ② 설명\n2 번 - ①, ③ 해설')],'explained')['rows'][1]['answer']==[1,3]
        assert extract([(1,'1 번 - ①, ?')],'explained')['rows'][0]['answer'] is None
        assert not extract([(1,'1) 3\n3) 2')],'compact')['sequential']
        print('PASS: mixed written answers, multiple choices, malformed tail, missing number')
        return
    if not all((a.pdf,a.layout,a.output)):
        p.error('PDF, layout and new output directory required')
    import pypdfium2 as pdf
    d=pdf.PdfDocument(str(a.pdf))
    pages=[(i+1,d[i].get_textpage().get_text_range()) for i in range(len(d))]
    result=extract(pages,a.layout,a.footer)
    # Preserve the unchanged parser outcome before this layout-specific adaptation.
    baseline=audit(pages,[], 'trial')
    result.update(source=str(a.pdf),sha256=hashlib.sha256(a.pdf.read_bytes()).hexdigest(),
                  pages=len(d),method='PDF text layer; no OCR',layout=a.layout,
                  excluded_footer=a.footer,baseline_rows=len(baseline['rows']),baseline_issues=baseline['issues'])
    a.output.mkdir(parents=True,exist_ok=False)
    (a.output/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    e=html.escape
    body=''.join(f'<tr><td>{r["question"]}</td><td>{r["page"]}</td><td>{r["kind"]}</td><td>{e(r["display"])}</td></tr>' for r in result['rows'])
    (a.output/'report.html').write_text('<!doctype html><meta charset="utf-8"><title>답지 추출 검토</title><style>body{font:17px/1.6 sans-serif;margin:32px}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:8px}td:last-child{max-width:850px}</style><h1>'+e(a.pdf.name)+'</h1><p>PDF 텍스트 추출. text_review는 문장·수정형 원문 보존이며 자동 채점 지원을 뜻하지 않습니다.</p><table><tr><th>문항</th><th>쪽</th><th>분류</th><th>추출 내용</th></tr>'+body+'</table>',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False))


if __name__=='__main__':
    main()
