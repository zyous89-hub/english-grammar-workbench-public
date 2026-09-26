"""121: two sequential, local post-OCR experiments; no production rule promotion."""
import argparse
from collections import Counter
import hashlib
import html
import json
import math
import os
from pathlib import Path
import time

import cv2
import numpy as np

from tools.classify_grid_stages import question_review, compare_label, overlaps


def radius(x, y, ellipse):
    (cx, cy), (a, b), angle = ellipse
    t = math.radians(angle)
    u, v = (x-cx)*math.cos(t)+(y-cy)*math.sin(t), -(x-cx)*math.sin(t)+(y-cy)*math.cos(t)
    return np.sqrt((2*u/a)**2+(2*v/b)**2)


def circles(gray, *, reject_boxes=False):
    """Frozen experimental thresholds; broken/clipped rings can be missed."""
    mask = np.uint8(gray < 195)*255
    contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    found = []
    for contour in contours:
        if len(contour) < 20:
            continue
        if reject_boxes and len(cv2.approxPolyDP(contour,.025*cv2.arcLength(contour,True),True))<=4:
            continue
        ellipse = cv2.fitEllipse(contour)
        (cx, cy), (a, b), angle = ellipse
        if not (min(a,b) >= max(20, .30*min(gray.shape)) and max(a,b)/min(a,b) <= 2):
            continue
        if not (0 <= cx < gray.shape[1] and 0 <= cy < gray.shape[0]):
            continue
        if math.pi*a*b/4 < .08*gray.size:
            continue
        pts = contour[:,0,:]
        errors = np.abs(radius(pts[:,0], pts[:,1], ellipse)-1)
        if float(errors.mean()) <= .10 and float(np.quantile(errors,.9)) <= .20:
            found.append(dict(ellipse=ellipse, mean_error=float(errors.mean())))
    return found


def connected_circles(gray):
    """Fallback for rings joined to a box; keep the original detector unchanged."""
    found=circles(gray,reject_boxes=True)
    if found:
        return found
    size=min(gray.shape)
    proposed=cv2.HoughCircles(cv2.GaussianBlur(gray,(5,5),0),cv2.HOUGH_GRADIENT,
                             1,size*.2,param1=100,param2=25,
                             minRadius=max(10,int(size*.2)),maxRadius=int(size*.48))
    if proposed is None:
        return []
    yy,xx=np.where(gray<195)
    for cx,cy,r in proposed[0]:
        near=np.abs(np.hypot(xx-cx,yy-cy)-r)<=max(2.5,.1*r)
        angles=np.mod(np.arctan2(yy[near]-cy,xx[near]-cx),2*np.pi)
        bins=set((angles*36/(2*np.pi)).astype(int).tolist())
        # ponytail: angular ink support, not semantic recognition of selection/cancellation.
        if len(bins)>=27:
            found.append(dict(ellipse=((float(cx),float(cy)),(float(2*r),float(2*r)),0),
                              method='connected_arc',angular_coverage=len(bins)/36))
    return found


def duplicate(blocker, candidate, gray, detected):
    """Same image coordinates + ring interior contains almost only candidate ink.

    This is a geometric proxy, not proof of semantic equality or cancellation.
    """
    x,y,X,Y = blocker['box']; a,b,A,B = candidate['box']
    if not (x<=a and y<=b and X>=A and Y>=B):
        return False
    h,w = gray.shape
    # Input was stripped of the existing 10-pixel white border before detection.
    sx,sy = w/(X-x),h/(Y-y)
    bounds = ((a-x-2)*sx, (b-y-2)*sy, (A-x+2)*sx, (B-y+2)*sy)
    yy,xx = np.indices(gray.shape)
    covered = (xx>=bounds[0]) & (xx<=bounds[2]) & (yy>=bounds[1]) & (yy<=bounds[3])
    center = ((a+A-2*x)*sx/2, (b+B-2*y)*sy/2)
    for item in detected:
        ellipse = item['ellipse']
        if radius(*center,ellipse) > .65:
            continue
        interior = (radius(xx,yy,ellipse)<.72) & (gray<195)
        total = int(interior.sum())
        if total >= 8 and int((interior & ~covered).sum())/total <= .05:
            return True
    return False


def exemptions(regions, evidence, mode):
    if mode not in ('broad','duplicate'):
        raise ValueError(mode)
    candidates = [r for r in regions if r['stage']==0]
    accepted = []
    for r in regions:
        if r['reason'] not in ('6','7') or r['id'] not in evidence:
            continue
        e=evidence[r['id']]
        related=[c for c in candidates if overlaps(c['box'],r['box'])]
        if not related or not e['circles']:
            continue
        if mode=='broad' or all(c['id'] in e['duplicates'] for c in related):
            accepted.append(r['id'])
    return accepted


def run(source, pages, transcription, output, selected_pages=None, selected_questions=None, circle_detector='contour'):
    detector={'contour':circles,'connected-arcs':connected_circles}[circle_detector]
    if output.exists():
        raise ValueError('Use a new output directory')
    tracked={}
    def read(p):
        raw=p.read_bytes(); tracked[str(p.resolve())]=hashlib.sha256(raw).hexdigest()
        return json.loads(raw)
    base=read(source); assert len(base['runs'])==1
    saved=base['runs'][0]
    if selected_pages is not None:
        if not selected_pages or not set(selected_pages) <= {q['page'] for q in saved['questions']}:
            raise ValueError('Requested pages are missing from the source')
        questions=[q for q in saved['questions'] if q['page'] in selected_pages]
        ids={q['id'] for q in questions}
        saved={**saved,'questions':questions,'regions':[r for r in saved['regions'] if r['question'] in ids]}
    if selected_questions is not None:
        if not selected_questions or not set(selected_questions) <= {q['id'] for q in saved['questions']}:
            raise ValueError('Requested questions are missing from the selected source')
        saved={**saved,'questions':[q for q in saved['questions'] if q['id'] in selected_questions],
               'regions':[r for r in saved['regions'] if r['question'] in selected_questions]}
    scope=sorted({q['page'] for q in saved['questions']})
    baseline=dict(Counter(q['comparison']['status'] for q in saved['questions']))
    alignment={p['page']:p for p in read(pages)}
    labels={q['id']:q for q in read(transcription)['rows']}
    assert all(labels[q['id']]['confirmed_by_user'] for q in saved['questions'])
    regions=saved['regions']; evidence={}
    for q in saved['questions']:
        assigned=[r for r in regions if r['question']==q['id']]
        assert question_review(assigned,q['review']['key'] and ','.join(map(str,q['review']['key'])),alignment[q['page']])==q['review']
        candidates=[r for r in assigned if r['stage']==0]
        for r in assigned:
            if r['reason'] not in ('6','7') or not any(overlaps(r['box'],c['box']) for c in candidates):
                continue
            path=(source.parent/r['input']).resolve()
            raw=path.read_bytes(); tracked[str(path)]=hashlib.sha256(raw).hexdigest()
            image=cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_GRAYSCALE)
            if image is None or min(image.shape)<=20:
                raise ValueError(f'Invalid crop: {path}')
            gray=image[10:-10,10:-10]; detected=detector(gray)
            evidence[r['id']]=dict(circles=detected,duplicates=[c['id'] for c in candidates if duplicate(r,c,gray,detected)])
    output.mkdir(parents=True)
    summaries={}; all_rows={}
    # Sequential by construction: each full set finishes before the next starts.
    for mode in ('broad','duplicate'):
        started=time.perf_counter(); rows=[]
        for q in saved['questions']:
            assigned=[r for r in regions if r['question']==q['id']]
            allowed=exemptions(assigned,evidence,mode)
            answer=','.join(map(str,q['review']['key'])) if q['review']['key'] else ''
            review=question_review(assigned,answer,alignment[q['page']],f08_exemptions=allowed)
            comparison=compare_label(review['selection'],labels[q['id']],review['key'])
            rows.append(dict(id=q['id'],page=q['page'],expected=q['expected'],review=review,
                             comparison=comparison,exemptions=allowed,changed=review!=q['review'],
                             context=os.path.relpath((source.parent/q['context']).resolve(),output).replace('\\','/')))
        summary=dict(questions=len(rows),counts=dict(Counter(q['comparison']['status'] for q in rows)),
                     pages=scope,regions=len(regions),baseline=baseline,circle_detector=circle_detector,
                     by_page={str(page):dict(questions=sum(q['page']==page for q in rows),
                         baseline=dict(Counter(q['comparison']['status'] for q in saved['questions'] if q['page']==page)),
                         counts=dict(Counter(q['comparison']['status'] for q in rows if q['page']==page))) for page in scope},
                     grading=dict(Counter(q['review']['status'] for q in rows)),
                     changed=[q['id'] for q in rows if q['changed']],
                     false_correct=sum(q['comparison']['false_correct'] for q in rows),
                     false_incorrect=sum(q['comparison']['false_incorrect'] for q in rows),
                     elapsed_seconds=time.perf_counter()-started)
        summaries[mode]=summary; all_rows[mode]=rows
        (output/f'{mode}.json').write_text(json.dumps(dict(summary=summary,rows=rows),ensure_ascii=False,indent=2),encoding='utf-8')
        report(output/f'{mode}.html',mode,summary,rows)
        print(mode,json.dumps(summary,ensure_ascii=False),flush=True)
    for p,h in tracked.items():
        assert hashlib.sha256(Path(p).read_bytes()).hexdigest()==h,p
    (output/'evidence.json').write_text(json.dumps(dict(detector=evidence,source_sha256=tracked),ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'summary.json').write_text(json.dumps(summaries,ensure_ascii=False,indent=2),encoding='utf-8')
    report(output/'report.html','compare',summaries,all_rows)


def report(path,mode,summary,rows):
    titles={'broad':'사용자안 · 동그라미 조각 예외','duplicate':'제안안 · 숫자와 중복된 동그라미 조각만 예외','compare':'F08(b) 두 조건 비교'}
    esc=lambda s:html.escape(str(s))
    common=summary['broad'] if mode=='compare' else summary
    content='<p>원 검출: '+('연결된 표시 보조 검출 적용' if common['circle_detector']=='connected-arcs' else '기존 윤곽 검출')+'</p>'
    if mode=='compare':
        for key,s in summary.items():
            content+=f'<h2><a href="{key}.html">{titles[key]}</a></h2><p>전사 일치 {s["counts"].get("전사 일치",0)} · 보류 {s["counts"].get("보류",0)} · 전사 불일치 {s["counts"].get("전사 불일치",0)} · 오답→정답 {s["false_correct"]}</p>'
            for page,counts in s['by_page'].items():
                content+=f'<p>{page}쪽 · {counts["questions"]}문항: 전사 일치 {counts["counts"].get("전사 일치",0)}, 보류 {counts["counts"].get("보류",0)} (기준 전사 일치 {counts["baseline"].get("전사 일치",0)}, 보류 {counts["baseline"].get("보류",0)})</p>'
        content+=f'<p>각 링크에서 전체 {common["questions"]}문항과 변경 문항의 원래 문항 이미지를 확인할 수 있습니다.</p>'
    else:
        content+=f'<p><a href="report.html">두 조건 비교로 돌아가기</a></p><p>전사 일치 {summary["counts"].get("전사 일치",0)} / 보류 {summary["counts"].get("보류",0)} / 변경 {len(summary["changed"])}문항</p><label><input id="changed" type="checkbox"> 변경 문항만 보기</label>'
        for q in rows:
            v=q['review']; marks='변경' if q['changed'] else '유지'
            content+=f'<details data-changed="{int(q["changed"])}"><summary>{esc(q["id"])} · {marks} · {esc(q["comparison"]["status"])} · 채점: {esc(v["status"])}</summary><p>전사: {esc(q["expected"])} / 자동 확정: {esc(v["selection"])} / 후보: {esc(v["proposed_selection"])}</p><p>예외 조각: {esc(q["exemptions"])} / 남은 보류 사유: {esc([x["rule"]+":"+x["code"] for x in v["reasons"]])}</p><img loading="lazy" src="{esc(q["context"])}" alt="{esc(q["id"])} 원래 문항"></details>'
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>F08(b) 조건 비교</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:1000px;margin:30px auto;padding:0 18px;background:#f4f6fa;color:#182333}a{color:#1659aa}details{background:white;margin:10px 0;padding:14px;border:1px solid #ccd5df;border-radius:8px;overflow-wrap:anywhere}summary{cursor:pointer}img{display:block;max-width:100%;height:auto}h1{font-size:25px}p{overflow-wrap:anywhere}</style>'''
    page+=f'<h1>{titles[mode]}</h1><p>{esc(", ".join(map(str,common["pages"])))}쪽 · {common["questions"]}문항 · 6000 / 0.7 / 3 · 076 알파벳 보존 입력. 같은 기존 OCR로 순차 재채점했습니다. 기준 결과는 전사 일치 {common["baseline"].get("전사 일치",0)} / 보류 {common["baseline"].get("보류",0)}입니다.</p><p>동그라미 자동 검출은 시험용입니다. 문항 번호·전사를 예외 결정에 사용하지 않았습니다. 이 자료로 규칙을 개발했으므로 독립 성능 평가가 아닙니다. 원 안의 다른 필기·취소 의미를 완전히 판별하지 못합니다.</p>'+content
    page+='''<script>const c=document.querySelector('#changed');if(c)c.onchange=()=>document.querySelectorAll('details').forEach(d=>d.hidden=c.checked&&d.dataset.changed!=='1');</script></html>'''
    path.write_text(page,encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('source',type=Path);p.add_argument('pages',type=Path)
    p.add_argument('transcription',type=Path);p.add_argument('output',type=Path)
    p.add_argument('--selected-pages',type=int,nargs='+')
    p.add_argument('--selected-questions',nargs='+')
    p.add_argument('--circle-detector',choices=['contour','connected-arcs'],default='contour')
    a=p.parse_args();run(a.source,a.pages,a.transcription,a.output,a.selected_pages,a.selected_questions,a.circle_detector)
