"""Sequential 27-combination experiment. Each stage runs once; failures are retained."""
import argparse
import hashlib
import html
import itertools
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time


def combinations():
    items = list(itertools.product((5000, 6000, 7000), (0.6, 0.7, 0.8), (2, 3, 4)))
    items.remove((6000, 0.7, 3))
    random.Random(20260926).shuffle(items)
    return [(6000, 0.7, 3), *items]


def read(p):
    return json.loads(Path(p).read_text(encoding="utf-8"))


def save(p, value):
    Path(p).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def report(output, results):
    cfg = read(output/"manifest.json")["config"]
    page_number = cfg.get("page", 18)
    rows = []
    for r in results:
        counts = r.get('counts', {})
        link = f'<a href="{r["id"]}/ocr/report-light.html">개별 보고서</a>' if (output/r['id']/'ocr/report-light.html').exists() else ''
        selections = ' / '.join(f'{e["id"].split("-q")[-1]}번: ' + (','.join(map(str,e['selection'])) if e['selection'] is not None else '보류') for e in r.get('evaluation', []))
        rows.append('<tr>' + ''.join(f'<td>{html.escape(str(x))}</td>' for x in
            [r['order'], r['features'], r['ratio'], r['ransac'], '완료' if r['status']=='completed' else '실패',
             counts.get('정답', 0), counts.get('오답', 0), counts.get('보류', 0),
             r.get('ocr_calls', ''), round(r['seconds'], 2), selections]) + f'<td>{link}</td></tr>')
    (output/'report.html').write_text('''<!doctype html><html lang="ko"><meta charset="utf-8"><title>27조합 순차 실험</title>
<style>body{font:16px/1.6 "Malgun Gothic",sans-serif;margin:25px}table{border-collapse:collapse}td,th{border:1px solid #bbc;padding:7px}th{background:#eef3f8}a{color:#156}</style>
<h1>PAGE_NUMBER쪽 · 27개 정렬 조합 순차 실험</h1><p>각 조합 1회. 076 삭제·보존 규칙을 고정했습니다. 정답/오답/보류는 자동 판정이며 실제 OCR 정확도가 아닙니다. 학생 답의 교사 확정 라벨은 없습니다. 미완료 조합은 오류 로그를 보존합니다.</p>
<table><tr><th>순서</th><th>특징점</th><th>비율</th><th>RANSAC</th><th>실행 상태</th><th>정답</th><th>오답</th><th>보류</th><th>OCR 수</th><th>총 초</th><th>문항별 채택 답</th><th>검토</th></tr>'''+''.join(rows)+'</table></html>', encoding='utf-8')
    report_path = output/'report.html'
    report_path.write_text(report_path.read_text(encoding='utf-8').replace('PAGE_NUMBER', str(page_number)), encoding='utf-8')


def run(config_path, output):
    cfg = read(config_path)
    expected = read(cfg['previous'])
    expected_ids = {q['id'] for q in expected}
    assert expected_ids and len(expected_ids) == len(expected)
    assert len({q['page'] for q in expected}) == 1
    cfg['page'] = expected[0]['page']
    output.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONUTF8='1', OMP_NUM_THREADS='4', MKL_NUM_THREADS='4',
               OPENBLAS_NUM_THREADS='4', OPENCV_FOR_THREADS_NUM='4')
    tracked = [Path(cfg[k]) for k in ('original', 'answer_key', 'config', 'previous', 'review')]
    tracked += sorted(Path(cfg['student_dir']).glob('*.jpg'))
    tracked += [Path('tools')/n for n in ('prepare_ocr_sources.py', 'ocr_source_inputs.py',
        'extract_added_ink.py', 'run_added_ink_ocr.py', 'grade_added_ink.py', 'ocr_reference_filter.py', 'ocr_background_filter.py')]
    hashes = {str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
    save(output/'manifest.json', dict(config=cfg, combinations=combinations(), hashes=hashes,
         thread_environment_limit=4, paddle_cpu_threads='unchanged library default (10)',
         policy='one attempt per combination, sequential blocking subprocesses, no retry'))
    results = []
    for order, (features, ratio, ransac) in enumerate(combinations(), 1):
        ident = f'f{features}-m{ratio:.1f}-r{ransac}'
        dest = output/ident
        dest.mkdir()
        result = dict(id=ident, order=order, features=features, ratio=ratio, ransac=ransac,
                      status='running', stages={})
        start = time.perf_counter()
        print(f'START {order}/27 {ident}', flush=True)
        try:
            for name, digest in hashes.items():
                if hashlib.sha256(Path(name).read_bytes()).hexdigest() != digest:
                    raise RuntimeError(f'Input/code changed: {name}')
            commands = [
                ('prepare', ['tools.prepare_ocr_sources', '--student-dir', cfg['student_dir'],
                    '--original', cfg['original'], '--answer-key', cfg['answer_key'],
                    '--key-first-page', str(cfg['key_first_page']), '--config', cfg['config'],
                    '--set-id', 'C', '--output', str(dest/'source'), '--features', str(features),
                    '--match-ratio', str(ratio), '--ransac-error', str(ransac)]),
                ('extract', ['tools.extract_added_ink', str(dest/'source'), str(dest/'input')]),
                ('ocr', ['tools.run_added_ink_ocr', str(dest/'input'), str(dest/'source'), str(dest/'ocr'), cfg['model_dir']]),
                ('grade', ['tools.grade_added_ink', str(dest/'source'), str(dest/'ocr'), cfg['previous'], cfg['review']])]
            # ponytail: blocking calls guarantee one job; no worker pool is needed.
            for stage, args in commands:
                t = time.perf_counter()
                with (dest/f'{stage}.log').open('w', encoding='utf-8') as log:
                    completed = subprocess.run([sys.executable, '-m', *args], env=env,
                        stdout=log, stderr=subprocess.STDOUT)
                result['stages'][stage] = dict(seconds=time.perf_counter()-t, exit_code=completed.returncode)
                if completed.returncode:
                    raise RuntimeError(f'{stage} failed: see {stage}.log')
                if stage == 'prepare':
                    qs = read(dest/'source/questions.json')
                    assert len(qs) == len(expected_ids) and {q['id'] for q in qs} == expected_ids
                    assert {q['page'] for q in qs} == {cfg['page']}
                    assert len(read(dest/'source/pages.json')) == 1
            evaluation = read(dest/'ocr/evaluation.json')
            summary = read(dest/'ocr/comparison.json')
            result.update(status='completed', counts=summary['semantic']['counts'], evaluation=evaluation,
                ocr_calls=summary['new_ocr_calls'], regions=summary['regions'],
                alignment=read(dest/'source/pages.json')[0])
        except Exception as exc:
            result.update(status='failed', error=str(exc))
        result['seconds'] = time.perf_counter()-start
        results.append(result)
        save(dest/'run.json', result)
        save(output/'results.json', results)
        report(output, results)
        print(f'END {order}/27 {ident}: {result["status"]} {result["seconds"]:.1f}s {result.get("counts", result.get("error"))}', flush=True)
    assert len(results) == 27 and len({r['id'] for r in results}) == 27


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('config', nargs='?', type=Path)
    parser.add_argument('output', nargs='?', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.check:
        grid = combinations()
        assert len(grid) == len(set(grid)) == 27
        assert grid[0] == (6000, .7, 3)
        assert set(grid) == set(itertools.product((5000,6000,7000),(.6,.7,.8),(2,3,4)))
        from tempfile import TemporaryDirectory
        for page in (4, 18):
            with TemporaryDirectory() as directory:
                root = Path(directory)
                save(root/'manifest.json', {'config': {'page': page}})
                report(root, [])
                assert f'<h1>{page}쪽' in (root/'report.html').read_text(encoding='utf-8')
        print('PASS: 27 unique combinations, baseline first, page 4/18 headings')
    elif args.config and args.output:
        run(args.config, args.output)
    else:
        parser.error('config and output are required')
