"""Local review report; transcription is used only to evaluate recommendations."""
import argparse
import base64
import html
import json
from pathlib import Path

from src.result_files import image_path, load_result
from tools.page_first_ocr import read, save, sha
from tools.classify_grid_stages import REASONS


def report(root, transcription, output, causes=None):
    if output.exists():
        raise FileExistsError(output)
    labels = {q['id']:q for q in read(transcription)['rows']}
    cause_rows = ({mode:{q['id']:q for q in rows} for mode,rows in read(causes)['policies'].items()}
                  if causes else {})
    images = {}; sections = []; summary = {}
    esc = lambda value: html.escape(str(value))

    def picture(folder, evidence):
        path = image_path(folder, evidence['path'])
        digest = sha(path)
        if digest not in images:
            mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
            images[digest] = dict(id=f'img{len(images)}',
                data=f'data:{mime};base64,'+base64.b64encode(path.read_bytes()).decode('ascii'))
        asset = images[digest]['id']
        return f'<figure><img loading="lazy" data-asset="{asset}" alt="{esc(evidence["label"])}"><figcaption>{esc(evidence["label"])}</figcaption></figure>'

    for mode, name in [('duplicate','기본 · 제안안'), ('broad','참고 · 사용자안 · 독립 검증에서 틀린 자동확정 1건')]:
        result = load_result(root/mode/'result.json')
        recs = {q['id']:q for q in read(root/mode/'recommendations.json')['recommendations']}
        matches = sum(bool(labels[qid].get('confirmed_by_user')) and not labels[qid].get('needs_review')
                      and labels[qid].get('numeric_answer') == ['①②③④⑤'.index(r['symbol'])+1]
                      for qid,r in recs.items())
        display_recommendations = bool(recs) and matches/len(recs) >= .9
        audit = dict(questions=len(result['questions']), automatic=0, held=0,
                     recommended=0, matched=0, wrong=[], unverified=[], dual_confirmed=0,
                     display_recommendations=display_recommendations)
        for q in result['questions']:
            rec = recs.get(q['id'])
            audit['held' if q['judgement']=='보류' else 'automatic'] += 1
            wrong = False; evaluation = ''
            proofs = [e for e in q['evidence_images'] if e['id']=='choice-mark-recommendation']
            agreements = [e for e in q['evidence_images'] if e['id'].startswith('two-evidence-')]
            resolutions = [e for e in q['evidence_images'] if e['id'].startswith('same-answer-')]
            audit['dual_confirmed'] += bool(agreements)
            if bool(rec) != bool(proofs) or len(proofs) > 1:
                raise ValueError('Recommendation manifest and evidence disagree')
            if rec:
                if q['judgement'] != '보류':
                    raise ValueError('Recommendation on an automatic result')
                audit['recommended'] += 1
                label = labels[q['id']]
                expected = label.get('numeric_answer')
                answer = ['①②③④⑤'.index(rec['symbol'])+1]
                if not label.get('confirmed_by_user') or label.get('needs_review') or not expected:
                    evaluation = '평가 전사 미확정'
                    audit['unverified'].append(q['id'])
                elif answer == expected:
                    audit['matched'] += 1; evaluation = '확인 전사와 일치'
                else:
                    wrong = True; evaluation = '확인 전사와 불일치'
                    audit['wrong'].append(dict(id=q['id'], recommendation=rec['symbol'],
                                             transcription=label['transcription']))
                evaluation += f" · 확인 전사: {label['transcription']}"
            title = q['label']+' · '+q['judgement']
            if not display_recommendations:
                proofs = []; evaluation = ''
            if proofs:
                title += ' · '+proofs[0]['label']
            if agreements:
                title += ' · '+agreements[0]['label']
            if resolutions:
                title += ' · '+resolutions[0]['label']
            body = '<p class="evaluation">'+esc(evaluation)+'</p>' if evaluation else ''
            body += f'<p>읽은 답: {esc(q["read_answer"])} · 채점: {esc(q["judgement"])} · 답지: {esc(q["answer_key"])}</p>'
            body += '<ul>'+''.join('<li>'+esc(r['message'])+'</li>' for r in q['reasons'])+'</ul>'
            contexts = [e for e in q['evidence_images'] if e['id']=='context']
            checks = cause_rows.get(mode,{}).get(q['id'],{}).get('reason_audit',[])
            if checks:
                body += '<div class="scroll"><table><tr><th>검사 시점·사유</th><th>원인 조각</th><th>해소 여부</th></tr>'
                for check in checks:
                    ids = ', '.join(c['crop_id'].split('-page-')[-1] for c in check['causes']) or '특정 불가'
                    phase = '원래 사유' if check['phase']=='original' else '후보 적용 후 검사'
                    state = ('같은 답 표시로 해소 가능' if check['cleared'] else
                             '기존 후보 판정으로 재검사' if check['rule']=='no_candidate' and check['code'] in ('5','6','9') else '유지')
                    body += f'<tr><td>{esc(phase)} · {esc(check["rule"])} · {esc(REASONS[check["code"]])}</td><td>{esc(ids)}</td><td>{state}</td></tr>'
                body += '</table></div><p>후보 적용 후 검사는 원인 확인용입니다. 다른 사유가 남으면 자동확정하지 않습니다.</p>'
            body += '<div class="images">'+''.join(picture(root/mode, e) for e in proofs+agreements+resolutions+contexts[:1])+'</div>'
            sections.append(f'<details data-mode="{mode}" data-id="{esc(q["id"])}" data-held="{int(q["judgement"]=="보류")}" data-agreement="{int(bool(agreements))}" data-rec="{int(bool(rec) and display_recommendations)}" data-wrong="{int(wrong and display_recommendations)}"><summary>{esc(title)}</summary>{body}</details>')
        summary[mode] = audit
    rows = ''.join(f'<tr><td>{name}</td><td>{summary[mode]["automatic"]}</td><td>{summary[mode]["held"]}</td><td>{summary[mode]["recommended"]}</td><td>{summary[mode]["matched"]}</td><td>{len(summary[mode]["wrong"])}</td><td>{len(summary[mode]["unverified"])}</td></tr>' for mode,name in [('duplicate','기본 · 제안안'),('broad','참고 · 사용자안 · 독립 검증에서 틀린 자동확정 1건')])
    wrongs = ''.join('<p>'+name+': '+esc((', '.join(f"{q['id']} 추천 {q['recommendation']} / 전사 {q['transcription']}" for q in summary[mode]['wrong']) or '없음') if summary[mode]['display_recommendations'] else '전사 일치율 90% 미달 또는 추천 없음: 추천 목록·이미지 미표시')+'</p>' for mode,name in [('duplicate','기본 · 제안안'),('broad','참고 · 사용자안 · 독립 검증에서 틀린 자동확정 1건')])
    assets = json.dumps({v['id']:v['data'] for v in images.values()}).replace('<','\\u003c')
    page = '''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="icon" href="data:,"><title>보류 문항 추천 답 · EGW4</title><style>
*{box-sizing:border-box}body{font:16px/1.7 "Malgun Gothic",sans-serif;color:#193548;background:#f3f6f8;max-width:1180px;margin:24px auto;padding:0 18px}h1{font-size:27px}p,summary,li{overflow-wrap:anywhere}.notice{background:#fff3d6;border-left:4px solid #bd822b;padding:14px}table{border-collapse:collapse;width:100%;background:#fff}th,td{padding:9px;border-bottom:1px solid #ccd5df;text-align:left}.scroll{overflow:auto}.controls{display:flex;flex-wrap:wrap;gap:18px;margin:20px 0}.controls label{min-width:0;max-width:100%}select{font:inherit;max-width:100%;padding:7px}details{background:#fff;border:1px solid #ccd5df;border-radius:8px;padding:14px;margin:12px 0}summary{cursor:pointer;font-weight:bold}.images{display:flex;flex-wrap:wrap;gap:18px}figure{margin:10px 0;max-width:100%}img{max-width:100%;max-height:700px;object-fit:contain}figcaption{font-size:14px}.evaluation{color:#97481e;font-weight:bold}:focus-visible{outline:3px solid #a97118}@media(max-width:600px){body{padding:0 12px}h1{font-size:23px}th,td{padding:5px;font-size:13px}}
</style><h1>보류 문항 추천 답 · EGW4</h1><p class="notice"><b>추천은 교사 확인용이며 자동확정이 아닙니다.</b> 확정 답·채점·보류 사유는 기존 결과 그대로입니다. 답지가 복수 정답인 문항에는 추천하지 않습니다. 체크의 윗획·소거 표시 때문에 틀린 추천이 있으니 번호 주변과 원래 문항을 함께 확인하세요.</p><div class="scroll"><table><tr><th>정책</th><th>자동확정</th><th>보류</th><th>추천</th><th>전사 일치</th><th>불일치</th><th>평가 미확정</th></tr>'''+rows+'''</table></div><p>개발용 기존 134문항 평가입니다. 전사 일치는 학생이 쓴 답과의 비교이며 답지상 정답률이 아닙니다. 전사는 추천 생성에 사용하지 않았습니다.</p><details id="wrong-list"><summary>틀린 추천 목록</summary>'''+wrongs+'''</details><div class="controls"><label>정책 <select id="policy"><option value="duplicate">기본 · 제안안</option><option value="broad">참고 · 사용자안 · 독립 검증에서 틀린 자동확정 1건</option></select></label><label>보기 <select id="view"><option value="held">보류 전체</option><option value="rec">추천 있는 보류</option><option value="wrong">틀린 추천과 이미지</option><option value="agreement">두 증거로 새로 확정</option><option value="all">전체 문항</option></select></label></div><p id="count" aria-live="polite"></p>'''+''.join(sections)+'''<script>const images='''+assets+''';document.querySelectorAll('img[data-asset]').forEach(i=>i.src=images[i.dataset.asset]);const policy=document.querySelector('#policy'),view=document.querySelector('#view');function filter(){let n=0;document.querySelectorAll('details[data-mode]').forEach(d=>{d.hidden=d.dataset.mode!==policy.value||(view.value!=='all'&&d.dataset[view.value]!=='1');if(!d.hidden)n++});document.querySelector('#count').textContent=n+'문항 표시'}policy.onchange=view.onchange=filter;filter();</script></html>'''
    if any(s['dual_confirmed'] for s in summary.values()):
        page = page.replace('보류 문항 추천 답 · EGW4', '채점 결과 · 두 증거 일치 · EGW4')
        page = page.replace('확정 답·채점·보류 사유는 기존 결과 그대로입니다.',
                            '“두 증거 일치” 문항은 독립된 손글씨와 선택 표시가 일치해 새로 자동확정됐습니다.')
    output.write_text(page, encoding='utf-8')
    save(output.with_suffix('.json'), summary)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for name in ('root', 'transcription', 'output'):
        parser.add_argument(name, type=Path)
    parser.add_argument('--causes', type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.root, args.transcription, args.output, args.causes), ensure_ascii=False))
