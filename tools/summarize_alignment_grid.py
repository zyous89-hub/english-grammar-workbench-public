"""Validate the finished single-attempt grid without rerunning any recognition."""
import hashlib
import html
import json
from pathlib import Path
import statistics
import sys

from tools.run_alignment_grid import combinations, read, save, report


def summarize(root):
    runs = read(root/'results.json')
    cfg = read(root/'manifest.json')['config']
    expected_ids = {q['id'] for q in read(cfg['previous'])}
    assert len(runs) == 27
    assert {(r['features'],r['ratio'],r['ransac']) for r in runs} == set(combinations())
    metrics = []
    signatures = {}
    for r in runs:
        if r['status'] != 'completed':
            continue
        rows = read(root/r['id']/'ocr/results.json')
        evaluation = read(root/r['id']/'ocr/evaluation.json')
        assert len(evaluation) == len(expected_ids) and {e['id'] for e in evaluation} == expected_ids
        assert len({x['id'] for x in rows}) == len(rows)
        assert sum(x['ocr_executed'] for x in rows) == r['ocr_calls']
        for x in rows:
            assert hashlib.sha256(Path(x['input']).read_bytes()).hexdigest() == x['input_sha256']
        signature = json.dumps([(e['id'],e['selection'],e['status']) for e in evaluation],ensure_ascii=False)
        signatures.setdefault(signature, []).append(r['id'])
        scores = [x['score'] for x in rows if x['ocr_executed'] and not x['answer_excluded']]
        metrics.append(dict(id=r['id'],features=r['features'],ratio=r['ratio'],ransac=r['ransac'],
            inliers=r['alignment']['inliers'],median_error=r['alignment']['median_error'],
            crops=len(rows),ocr_calls=r['ocr_calls'],median_score=statistics.median(scores) if scores else None,
            total_seconds=r['seconds'],stages=r['stages'],counts=r['counts']))
    summary = dict(attempts=len(runs),completed=len(metrics),failed=27-len(metrics),
        total_seconds=sum(r['seconds'] for r in runs),ocr_calls=sum(m['ocr_calls'] for m in metrics),
        grading_groups=list(signatures.values()),metrics=metrics,
        limitations=['One fixed development page; no independent accuracy labels.',
          'OCR score and inlier error are diagnostics, not accuracy rankings.',
          'Baseline ran first; initialization/cache effects may affect timing.',
          'Thread environment set to 4; Paddle inference default cpu_threads=10 was not overridden.',
          'No peak-memory measurement; one combination at a time.'])
    save(root/'summary.json', summary)
    report(root,runs)
    table='<h2>정렬·OCR 진단값</h2><p>이 값만으로 최적 조합을 고르지 않습니다. 특히 RANSAC 오차가 다르면 정상 매칭으로 세는 기준도 다릅니다. 기준 조합은 최초 실행이라 시작 비용의 영향을 받을 수 있습니다.</p><table><tr><th>조합</th><th>정상 매칭</th><th>정렬 중앙 오차</th><th>조각</th><th>OCR 중앙 점수</th><th>준비 초</th><th>OCR 단계 초</th></tr>'
    for m in sorted(metrics,key=lambda x:(x['features'],x['ratio'],x['ransac'])):
        table += '<tr>'+''.join(f'<td>{html.escape(str(v))}</td>' for v in [m['id'],m['inliers'],round(m['median_error'],4),m['crops'],round(m['median_score'],4) if m['median_score'] is not None else '',round(m['stages']['prepare']['seconds'],2),round(m['stages']['ocr']['seconds'],2)])+'</tr>'
    page=root/'report.html'
    page.write_text(page.read_text(encoding='utf-8').replace('</html>',table+'</table><p>실행은 조합별 한 번씩 순차 진행했습니다. OCR 결과를 재사용하지 않았습니다. 이 결과는 학생의 실제 정답률이나 검증된 OCR 정확도가 아닙니다.</p></html>'),encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('metrics','grading_groups')},ensure_ascii=False,indent=2))
    print('grading group sizes:',[len(g) for g in summary['grading_groups']])


if __name__ == '__main__':
    summarize(Path(sys.argv[1]))
