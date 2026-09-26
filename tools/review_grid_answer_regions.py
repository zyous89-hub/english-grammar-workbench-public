"""Post-run diagnostic: read existing OCR near manually identified written answers."""
import argparse
from collections import Counter
import hashlib
import html
import json
from pathlib import Path

from tools.ocr_reference_filter import eligible_answer


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def project(box, matrix):
    points = []
    for x, y in [(box[0], box[1]), (box[2], box[1]), (box[2], box[3]), (box[0], box[3])]:
        z = matrix[2][0]*x + matrix[2][1]*y + matrix[2][2]
        points.append(((matrix[0][0]*x+matrix[0][1]*y+matrix[0][2])/z,
                       (matrix[1][0]*x+matrix[1][1]*y+matrix[1][2])/z))
    return [min(x for x,y in points), min(y for x,y in points),
            max(x for x,y in points), max(y for x,y in points)]


def inside(box, roi):
    x, y = (box[0]+box[2])/2, (box[1]+box[3])/2
    return roi[0] <= x <= roi[2] and roi[1] <= y <= roi[3]


def main(root, roi_path, labels_path):
    rois = read(roi_path)['pages']
    labels = read(labels_path)['rows']
    results = []
    for run in read(root/'results.json'):
        if run['status'] != 'completed':
            continue
        dest = root/run['id']
        pages = {p['page']:p for p in read(dest/'source/pages.json')}
        raw = read(dest/'ocr/results.json')
        qs = {q['id']:q['page'] for q in read(dest/'source/questions.json')}
        rows = []
        for label in labels:
            roi = project(rois[str(label['page'])][str(label['question'])], pages[label['page']]['matrix'])
            nearby = [r for r in raw if qs[r['id'].rsplit('-r',1)[0]] == label['page'] and inside(r['box'], roi)]
            # ponytail: this is a manual-position diagnostic, not automatic answer selection.
            numbers = sorted({n for r in nearby for n in (eligible_answer(r['text'], 1, 'student_candidate') or [])})
            expected = label['numeric_answer']
            status = ('special' if expected is None else 'no_numeric_read' if not numbers
                      else 'match' if numbers == sorted(expected) else 'mismatch')
            rows.append(dict(id=label['id'], expected=label['transcription'], numbers=numbers,
                             status=status, roi=roi, crops=[{k:r.get(k) for k in ('id','text','score','route','box')} for r in nearby]))
        results.append(dict(id=run['id'], order=run['order'], counts=dict(Counter(r['status'] for r in rows)), rows=rows))
    payload = dict(roi_sha256=hashlib.sha256(roi_path.read_bytes()).hexdigest(),
                   method='Manual answer locations; crop centers mapped by homography; union of strictly numeric outputs, ignoring confidence/route; nonnumeric outputs retained for review. Not independent model accuracy.', results=results)
    (root/'answer-region-review.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    e=lambda v:html.escape(str(v))
    table=[]
    for run in results:
        table.append('<details><summary>'+e(run['id'])+' '+e(run['counts'])+'</summary><table>')
        for row in run['rows']:
            text=' / '.join(f"{c['id']}: {c['text']} ({c['score']})" for c in row['crops'])
            table.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in [row['id'],row['expected'],row['numbers'],row['status'],text])+'</tr>')
        table.append('</table></details>')
    (root/'answer-region-review.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><title>답 위치 OCR 보조 검토</title><style>body{font:16px/1.6 sans-serif;margin:24px}td{border:1px solid #ccc;padding:6px}details{margin:14px 0}</style><h1>별도로 쓴 답의 위치 · OCR 보조 검토</h1><p>Codex가 원본에서 확인한 답 위치에 중심이 들어오는 조각만 모았습니다. 점수·경로와 무관하게 숫자로만 읽힌 출력의 합집합을 전사와 비교합니다. 문항 소속이 잘못된 조각도 같은 페이지의 위치로 찾습니다. 숫자가 아닌 출력은 표에 남지만 합집합에서 제외됩니다. 수동 위치 정보가 들어간 진단이며 자동 채택률·OCR 문자 정확도가 아닙니다. 특수 표시 3문항은 원문으로 검토합니다. 경계에 걸친 조각과 영문 풀이 전체는 이 지표로 평가할 수 없습니다.</p>'+''.join(table)+'</html>', encoding='utf-8')
    runs = read(root/'results.json')
    by_id = {r['id']: r for r in results}
    table = []
    for run in runs:
        c = run.get('transcription', {}).get('counts', {})
        d = by_id.get(run['id'], {}).get('counts', {})
        table.append('<tr>'+''.join('<td>'+e(v)+'</td>' for v in
            [run['order'], run['features'], run['ratio'], run['ransac'],
             d.get('match', ''), d.get('mismatch', ''), d.get('no_numeric_read', ''),
             c.get('일치', ''), c.get('불일치', 0), c.get('보류', ''), round(run['seconds'], 1)])+'</tr>')
    seconds = sum(r['seconds'] for r in runs)
    title = f'{len(results)}/36개 설정 완료 · 3·4·6·15·16쪽'
    page = '<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OCR 36개 설정 비교</title><style>body{font:16px/1.7 "Malgun Gothic",sans-serif;margin:24px;max-width:1400px}table{border-collapse:collapse;width:100%;min-width:800px}td,th{border:1px solid #bbc;padding:7px;text-align:center}th{background:#eef3f8}.scroll{overflow:auto}a{color:#14579b}</style><h1>'+title+'</h1>'
    page += f'<p>각 설정 1회·순차 실행. 누적 {seconds/60:.1f}분. 숫자 답 32문항 + 특수 표시 3문항. 교재 정답 대신 사용자 확인 전사와 비교했습니다.</p>'
    page += '<p><b>답 위치 보조 비교:</b> 사람이 원본에서 지정한 답 위치의 OCR 출력 중 숫자로 읽힌 결과를 모아 비교합니다. 신뢰도 기준을 적용하지 않습니다. 위치 정보를 사람이 제공하므로 자동 인식률이나 문자 정확도가 아닙니다. 숫자가 아닌 출력은 상세표에 남지만 숫자 집합에서 제외됩니다.</p><p><b>자동 채택 비교:</b> 기존 0.8 기준과 문항별 선택 규칙을 통과한 답을 비교합니다. 보류는 오독과 다릅니다. 특수 표시 3문항은 두 집계에서 제외하고 별도 검토합니다. 원 안 알파벳과 영어 풀이 전체의 정확도는 이 집계에 포함하지 않았습니다.</p>'
    page += '<p><a href="answer-region-review.html">답 위치별 OCR 원문</a> · <a href="report.html">자동 채택 및 문항 전체 OCR 원문</a> · <a href="summary.json">검증 집계 JSON</a></p>'
    page += '<div class="scroll"><table><tr>'+''.join('<th>'+s+'</th>' for s in ['순서','특징점','비율','RANSAC','위치 비교 일치','위치 비교 불일치','숫자 출력 없음','자동 일치','자동 불일치','자동 보류','초'])+'</tr>'+''.join(table)+'</table></div></html>'
    (root/'index.html').write_text(page, encoding='utf-8')
    print([(r['order'],r['counts']) for r in results])


if __name__ == '__main__':
    assert project([1,2,3,4], [[1,0,0],[0,1,0],[0,0,1]]) == [1,2,3,4]
    assert inside([1,2,3,4], [0,0,5,5]) and not inside([1,2,3,4], [4,4,5,5])
    p=argparse.ArgumentParser()
    p.add_argument('root',type=Path)
    p.add_argument('rois',type=Path)
    p.add_argument('labels',type=Path)
    a=p.parse_args()
    main(a.root,a.rois,a.labels)
