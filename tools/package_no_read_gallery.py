"""Package both policies' reason-5 crops as a self-contained ordered gallery."""
import argparse
import base64
import hashlib
import json
import re
from pathlib import Path


def package(root, output):
    if output.exists():
        raise ValueError('Use a new output file')
    assets, policies = {}, {}

    def asset(path):
        raw = path.read_bytes()
        key = hashlib.sha256(raw).hexdigest()
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg'}[path.suffix.lower()]
        assets.setdefault(key, f'data:{mime};base64,' + base64.b64encode(raw).decode('ascii'))
        return key

    for policy in ('broad', 'duplicate'):
        rows = json.loads((root / 'comparison' / f'{policy}.json').read_text(encoding='utf-8'))['rows']
        result_dir = root / 'result' / policy
        results = json.loads((result_dir / 'result.json').read_text(encoding='utf-8'))['questions']
        by_id = {q['id']: q for q in results}
        selected = []
        for row in rows:
            ids = {i for r in row['review']['reasons'] if r['code'] == '5' for i in r['crop_ids']}
            if not ids or row['review']['status'] != '보류':
                continue
            question = by_id[row['id']]
            proof = {im['id']: im for im in question['evidence_images']}
            crops = [dict(id=i, image=asset(result_dir / proof[i]['path']))
                     for i in sorted(ids, key=lambda i: int(i.rsplit('-r', 1)[1]))]
            selected.append(dict(id=row['id'], page=row['page'], crops=crops,
                                 context=asset(result_dir / proof['context']['path']),
                                 reasons=[r['message'] for r in question['reasons']]))
        selected.sort(key=lambda q: (q['page'], tuple(map(int, re.findall(r'\d+', q['id'])))))
        policies[policy] = selected
    payload = json.dumps(dict(policies=policies, assets=assets), ensure_ascii=False).replace('<', '\\u003c')
    page = '''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>OCR 인식 결과 없음 · 두 안 이미지 검토</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f3f5f8;color:#182c40;font:16px/1.65 system-ui,sans-serif}header,main{max-width:1100px;margin:auto;padding:20px}h1{font-size:26px;margin:0 0 8px}p{margin:8px 0}.muted{color:#506177}.toolbar{position:sticky;top:0;background:#fff;border-bottom:1px solid #cbd5df;padding:12px;z-index:1;display:flex;justify-content:center;gap:10px;flex-wrap:wrap}button,select{font:inherit;padding:8px 12px;border:1px solid #9aaabc;border-radius:6px;background:white;color:#182c40;max-width:100%}button{cursor:pointer}button:disabled{opacity:.4;cursor:default}button:focus-visible,select:focus-visible,summary:focus-visible{outline:3px solid #2370c3;outline-offset:2px}.card{background:white;border:1px solid #d4dde5;border-radius:10px;padding:18px;margin-bottom:18px}.crops{display:flex;gap:16px;flex-wrap:wrap}.crop{max-width:100%;padding:14px;border:1px solid #b9c8d6;border-radius:8px;text-align:left}.crop span{display:block;overflow-wrap:anywhere;margin-bottom:12px}.crop img{display:block;min-height:90px;max-height:260px;max-width:100%;width:auto;object-fit:contain;image-rendering:auto}.context{display:block;max-width:100%;height:auto;margin:12px auto}h2{font-size:21px}h3{font-size:18px}#position{font-weight:700}dialog{border:0;border-radius:10px;max-width:96vw;max-height:95vh;padding:18px}dialog::backdrop{background:#000a}dialog img{display:block;max-width:88vw;max-height:75vh;min-height:180px;object-fit:contain;margin:16px auto}summary{cursor:pointer;font-weight:600}@media(max-width:600px){header,main{padding:14px}.toolbar{gap:6px}h1{font-size:22px}.crop{width:100%}}</style></head><body>
<header><h1>OCR 인식 결과 없음 — 두 안 이미지 검토</h1><p id="totals"></p><p class="muted">141 재채점 결과 · OCR을 실행했지만 글자를 읽지 못한 조각만 모았습니다. 문항 전체가 무응답이라는 뜻은 아닙니다. 새 OCR이나 채점 변경은 없습니다.</p><p class="muted">쪽수 → 문항 → 조각 번호 순서입니다. 이전·다음 버튼 또는 키보드 ← →로 넘기고, 조각을 누르면 확대됩니다. 모든 사진이 이 파일에 포함되어 있습니다.</p></header>
<nav class="toolbar" aria-label="검토 이동"><label>검토안 <select id="policy"><option value="duplicate">기본 · 제안안</option><option value="broad">참고 · 사용자안 · 독립 검증에서 틀린 자동확정 1건</option></select></label><button id="prev">← 이전 문항</button><label>문항 <select id="jump"></select></label><button id="next">다음 문항 →</button></nav>
<main><p id="position" role="status" aria-live="polite"></p><section class="card"><h2 id="heading"></h2><h3>인식 결과가 없었던 조각</h3><div id="crops" class="crops"></div></section><section class="card"><details open><summary>학생 원래 문항 사진</summary><img id="context" class="context" alt="학생 원래 문항"></details></section><section class="card"><h3>이 안에 기록된 문항 보류 사유</h3><p id="reasons"></p><p class="muted">여러 조각에서 서로 다른 사유가 함께 기록될 수 있습니다.</p></section></main>
<dialog id="zoom"><button id="closeZoom">확대 닫기</button><p id="zoomLabel"></p><img id="zoomImage" alt="확대 조각"></dialog>
<script>const data=PAYLOAD;let index=0;const $=id=>document.getElementById(id);const rows=()=>data.policies[$('policy').value];
function counts(list){return list.length+'문항 · '+list.reduce((n,q)=>n+q.crops.length,0)+'개 조각'}
const signature=list=>JSON.stringify(list.map(q=>[q.id,q.crops.map(c=>c.id)]));
$('totals').textContent='사용자안 '+counts(data.policies.broad)+' / 제안안 '+counts(data.policies.duplicate)+(signature(data.policies.broad)===signature(data.policies.duplicate)?' — 해당 문항과 조각 목록이 같습니다.':'');
function draw(){const list=rows();const q=list[index];$('jump').value=String(index);$('prev').disabled=index===0;$('next').disabled=index===list.length-1;$('position').textContent=(index+1)+' / '+list.length+' 문항 · 이 문항의 해당 조각 '+q.crops.length+'개';$('heading').textContent=q.page+'쪽 · '+q.id;$('crops').replaceChildren();for(const c of q.crops){const button=document.createElement('button');button.className='crop';button.setAttribute('aria-label',c.id+' 확대');const label=document.createElement('span');label.textContent=c.id;const img=document.createElement('img');img.src=data.assets[c.image];img.alt=c.id+' OCR 입력 조각';button.append(label,img);button.onclick=()=>{$('zoomImage').src=img.src;$('zoomLabel').textContent=c.id;$('zoom').showModal()};$('crops').append(button)}$('context').src=data.assets[q.context];$('context').alt=q.id+' 학생 원래 문항';$('reasons').textContent=q.reasons.join(' / ')}
function fill(){const list=rows();$('jump').replaceChildren(...list.map((q,i)=>new Option((i+1)+'. '+q.page+'쪽 · '+q.id,String(i))));draw()}
function move(delta){index=Math.max(0,Math.min(rows().length-1,index+delta));draw();window.scrollTo({top:0,behavior:'instant'})}
$('policy').onchange=()=>{index=Math.min(index,rows().length-1);fill()};$('jump').onchange=()=>{index=Number($('jump').value);draw()};$('prev').onclick=()=>move(-1);$('next').onclick=()=>move(1);$('closeZoom').onclick=()=>$('zoom').close();document.addEventListener('keydown',e=>{if($('zoom').open||['SELECT','INPUT','TEXTAREA'].includes(e.target.tagName))return;if(e.key==='ArrowRight'){e.preventDefault();move(1)}if(e.key==='ArrowLeft'){e.preventDefault();move(-1)}});fill();</script></body></html>'''.replace('PAYLOAD', payload)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(page, encoding='utf-8')
    summary = {p: dict(questions=len(qs), crops=sum(len(q['crops']) for q in qs)) for p, qs in policies.items()}
    print(json.dumps(dict(policies=summary, unique_images=len(assets), bytes=output.stat().st_size), ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('root', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    package(args.root, args.output)
