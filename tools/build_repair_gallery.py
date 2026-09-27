"""Read-only diagnostic gallery; candidate detectors do not change grading."""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path

import cv2
import numpy as np

from tools.circle_inner_search import inner_image


def gray_residue(student, reference):
    def seeds(image, size):
        return cv2.morphologyEx(image, cv2.MORPH_CLOSE, np.ones((size, size), np.uint8)).astype(int) - image.astype(int) > 25
    def spread(mask):
        return cv2.dilate(mask.astype('uint8'), np.ones((7, 7), np.uint8)) > 0
    ink = seeds(student, 15)
    old, wide = seeds(reference, 15), seeds(reference, 31)
    added = wide & ~old
    gray = added & (reference >= 160) & (reference < 250)
    covered = ink & ~spread(old) & spread(gray)
    count = int(covered.sum())
    # Diagnostic screening only: deliberately expose thresholds in the report.
    return dict(candidate=count >= 100 and count >= .2 * max(1, int(ink.sum())),
                pixels=count, ink=int(ink.sum()), fraction=count / max(1, int(ink.sum())))


def crossed_components(labels, stats, box, zone):
    l, t, r, b = box; a, c, d, e = zone
    result = []
    for axis, edge, touching in [(0, a, l == a), (0, d, r == d), (1, c, t == c), (1, e, b == e)]:
        if not touching:
            continue
        for ident in np.unique(labels[t:b, l:r]):
            if not ident:
                continue
            x, y, w, h, area = stats[ident]
            low, high = (x, x+w) if axis == 0 else (y, y+h)
            if area >= 35 and low <= edge-3 and high >= edge+3:
                result.append((axis, edge, int(ident)))
    return result


def build(source, batch, comparison, output):
    if output.exists():
        raise ValueError('Use a fresh output directory')
    output.mkdir(parents=True)
    def read(path):
        return json.loads(path.read_text(encoding='utf-8'))
    rows = read(batch/'results.json'); by_id = {r['id']: r for r in rows}
    questions = {q['id']: q for q in read(source/'questions.json')}
    policies = {p: {q['id']: q for q in read(comparison/'result'/p/'result.json')['questions']}
                for p in ('broad', 'duplicate')}
    no_read = {p: {i for q in read(comparison/'comparison'/f'{p}.json')['rows']
                         for reason in q['review']['reasons'] if reason['code'] == '5' for i in reason['crop_ids']}
               for p in policies}
    assets, pages, crop_images = {}, {}, {}
    def put(raw, mime):
        key = hashlib.sha256(raw).hexdigest()
        assets.setdefault(key, f'data:{mime};base64,'+base64.b64encode(raw).decode('ascii'))
        return key
    def file(path):
        path = Path(path)
        return put(path.read_bytes(), 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg')
    def array(image):
        ok, encoded = cv2.imencode('.png', image)
        if not ok:
            raise ValueError('Image encoding failed')
        return put(encoded.tobytes(), 'image/png')
    for q in questions.values():
        if q['page'] in pages:
            continue
        stem = f"{q['set']}-{q['page']:02}"
        ref = cv2.imread(str(source/'pages'/f'{stem}-original.png'), 0)
        aligned = cv2.imread(str(source/'pages'/f'{stem}-aligned.jpg'), 0)
        ink = cv2.adaptiveThreshold(aligned, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 14)
        printed = cv2.dilate(np.uint8(ref < 195), np.ones((3, 3), np.uint8))
        _, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8((ink > 0) & (printed == 0)))
        pages[q['page']] = (ref, aligned, labels, stats)
    cases, boundaries = [], {}
    for r in rows:
        q = questions[r['question_id']]; ref, aligned, labels, stats = pages[q['page']]
        student = cv2.imread(r['source_input'], 0)[10:-10, 10:-10]
        l,t,rr,b = r['box']; reference = cv2.resize(ref[t:b,l:rr], (student.shape[1], student.shape[0]))
        probe = gray_residue(student, reference)
        categories = []
        if probe['candidate']:
            categories.append(('gray', '의심 사례 · 자동 선별', f"원본 회색 영역을 더 넓게 검출하면 기존 잔재 {probe['pixels']:,}픽셀({probe['fraction']:.1%})과 겹칩니다. 학생 획도 섞였는지 사진 확인이 필요합니다."))
        if any(r['id'] in ids for ids in no_read.values()):
            _, geometry = inner_image(cv2.imread(r['input'], 0))
            label = {'prepared':'분리 가능한 내부 획 있음', 'no_enclosure':'도형 검출 안 됨',
                     'unseparated_or_ambiguous':'테두리와 내부 획 분리 불가·모호', 'outside_ink':'도형 밖에 남는 획 있음',
                     'touching_ink':'남길 획과 지울 획이 접촉'}.get(geometry['status'], geometry['status'])
            categories.append(('no_read', '확인됨 · OCR 판독 결과 없음', '기존 OCR은 빈 결과입니다. 도형 분리 진단: '+label+'。 새 OCR은 하지 않았습니다.'))
        for axis, edge, component in crossed_components(labels, stats, r['box'], q['zone']):
            key = (q['page'], axis, edge, component)
            boundaries.setdefault(key, set()).add(r['id'])
        if categories:
            crop_images[r['id']] = [dict(label='원본의 같은 위치', image=array(reference)),
                                   dict(label='학생 조각 · 삭제 전', image=file(r['source_input'])),
                                   dict(label='실제 OCR 입력 · 삭제 후', image=file(r['input']))]
        for category, status, note in categories:
            if r['id']=='C-p1-s0-q27-r01' and category=='gray':
                status='확인됨 · 143 원본 회색 선 잔재'
            if r['id']=='C-p1-s0-q25-r06':
                note+=' 143에서 확인: 원본 중첩 0픽셀, 답 그림은 보존됐지만 테두리와 내부 획이 붙어 있습니다.'
            cases.append(dict(category=category, status=status, page=q['page'], ids=[r['id']], qids=[q['id']], note=note, images=crop_images[r['id']]))
    # Several connected parts of one drawing may cross the same boundary.
    # Merge only overlapping crop-ID groups; do not combine unrelated marks.
    groups = []
    for (page, axis, edge, component), ids in boundaries.items():
        merged = dict(key=(page, axis, edge), ids=set(ids), components={component})
        changed = True
        while changed:
            changed = False
            for group in groups[:]:
                if group['key'] == merged['key'] and group['ids'] & merged['ids']:
                    merged['ids'].update(group['ids']); merged['components'].update(group['components'])
                    groups.remove(group); changed = True
        groups.append(merged)
    for group in groups:
        page, axis, edge = group['key']; ids = group['ids']
        ids=sorted(ids); qids=sorted({by_id[i]['question_id'] for i in ids})
        ref, aligned, labels, stats=pages[page]
        boxes=[stats[i] for i in group['components']]
        l,t=max(0,min(int(s[0]) for s in boxes)-45),max(0,min(int(s[1]) for s in boxes)-45)
        r,b=min(ref.shape[1],max(int(s[0]+s[2]) for s in boxes)+45),min(ref.shape[0],max(int(s[1]+s[3]) for s in boxes)+45)
        # Context is capped to the page, never used as a new OCR input.
        view=cv2.cvtColor(aligned[t:b,l:r],cv2.COLOR_GRAY2BGR)
        if axis==1:cv2.line(view,(0,edge-t),(r-l-1,edge-t),(0,0,255),1)
        else:cv2.line(view,(edge-l,0),(edge-l,b-t-1),(0,0,255),1)
        images=[dict(label='경계 주변 학생 사진 · 빨간 선이 현재 문항 경계',image=array(view)),
                dict(label='같은 범위 원본',image=array(ref[t:b,l:r]))]
        for ident in ids:
            images.append(dict(label=ident+' · 현재 OCR 입력',image=file(by_id[ident]['input'])))
        confirmed=page==7 and axis==1 and edge==1407 and any(i.startswith('C-p1-s0-q42-') for i in ids)
        cases.append(dict(category='boundary',status='확인됨 · 143 q42→q43 분리' if confirmed else '의심 사례 · 경계 획 자동 선별',
                          page=page,ids=ids,qids=qids,images=images,
                          note=f"{'가로' if axis==1 else '세로'} 경계 {'y' if axis==1 else 'x'}={edge}. 원본 차이 영상의 연결된 획이 경계를 가로지릅니다. 인쇄 잔재일 수 있으며 실제 답의 소속은 교사 확인이 필요합니다. 사진은 저장된 정렬본 기준 진단입니다."))
    for case in cases:
        case['policies']={p: [dict(id=qid, judgement=policies[p][qid]['judgement'],reasons=[r['message'] for r in policies[p][qid]['reasons']]) for qid in case['qids']] for p in policies}
        case['contexts']=[dict(label=qid+' · 학생 원래 문항',image=file(questions[qid]['context'])) for qid in case['qids']]
    cases.sort(key=lambda c:(c['page'],tuple(map(int,re.findall(r'\d+',c['ids'][0]))),c['category']))
    summary={category:dict(cases=sum(c['category']==category for c in cases),
                          questions=len({q for c in cases if c['category']==category for q in c['qids']})) for category in ('gray','no_read','boundary')}
    data=dict(cases=cases,assets=assets,summary=summary)
    template=Path(__file__).with_name('repair_gallery.html').read_text(encoding='utf-8')
    (output/'report.html').write_text(template.replace('/*DATA*/',json.dumps(data,ensure_ascii=False).replace('<','\\u003c')),encoding='utf-8')
    (output/'diagnosis.json').write_text(json.dumps(dict(cases=cases,summary=summary),ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(dict(summary=summary,unique_images=len(assets),bytes=(output/'report.html').stat().st_size),ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('source','batch','comparison','output'):p.add_argument(name,type=Path)
    a=p.parse_args();build(a.source,a.batch,a.comparison,a.output)
