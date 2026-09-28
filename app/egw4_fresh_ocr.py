"""Fresh f5fed75 call orchestration, copied from the verified EGW3 fresh worker.
Only paths, progress and per-process network auditing differ; rules stay imported.
"""
import argparse
import os
from pathlib import Path
import sys
import time

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True


def main():
    parser = argparse.ArgumentParser()
    for name in ('source', 'output', 'model', 'audit-dir'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    from app.egw4_runner import install_network_audit, emit, run_child, engine_hashes, COMMIT
    install_network_audit(args.audit_dir/'fresh-worker.json')
    import cv2
    import numpy as np
    from tools.page_first_ocr import prepare, assign, read, save, sha
    from tools.ocr_retry_preprocess import peel_enclosures, normalise
    from tools.ocr_attached_enclosure import stable_reading, to_digit
    from tools.ocr_circle_strip import eligible, size_stable_reading, circle_strip_reading, peeled_circle_strip_reading
    from tools.circle_inner_search import reconcile
    engine = REPO
    engine_files = engine_hashes()
    source, dest, model = args.source.resolve(), args.output.resolve(), args.model.resolve()
    dest.mkdir(parents=True, exist_ok=False)
    pages = sorted(p['page'] for p in read(source/'pages.json'))
    tracked = {str(p): sha(p) for p in source.rglob('*') if p.is_file()}
    tracked.update({str(p): sha(p) for p in model.glob('inference.*')})

    def ocr(inputs, output):
        rows = read(inputs/'regions.json')
        if not rows:
            output.mkdir(); save(output/'results.json', [])
            save(output/'timing.json', dict(seconds=0, regions=0, ocr_executed=0,
                 stage1_skipped=0, answer_excluded=0, source=str(source), inputs=str(inputs), cached_ocr_reused=0))
            return []
        stage_name = 'ocr' if inputs.parent == dest else 'retry-'+inputs.parent.name
        def progress(done):
            pending = {r['page'] for r in rows[done:]}
            emit(stage=stage_name, done=len(set(pages)-pending), total=len(pages),
                 message=f'숫자를 판독하고 있습니다. 조각 {done}/{len(rows)}개')
        progress(0)
        run_child([sys.executable, str(REPO/'app/egw4_runner.py'), '--worker-module',
                   'tools.run_added_ink_ocr', str(args.audit_dir/(stage_name+'.json')),
                   str(inputs), str(source), str(output), str(model)],
                  inputs.parent/(inputs.name+'-ocr.log'),
                  lambda value: progress(value['done']) if 'done' in value else None)
        progress(len(rows))
        return read(output/'results.json')

    prepare(source, dest/'inputs', pages)
    original_rows = ocr(dest/'inputs', dest/'ocr')
    original = {r['id']: r for r in original_rows}
    current = {i: dict(r) for i, r in original.items()}
    eligible_ids = [i for i, r in original.items() if eligible(r)]
    grays = {i: cv2.imread(original[i]['input'], 0) for i in eligible_ids}
    peeled = {i: peel_enclosures(grays[i]) for i in eligible_ids}
    cache, phases = {}, {}

    def transform(ident, kind, callback):
        if kind == 'enclosure':
            return callback(normalise(peeled[ident]))
        if kind == 'hull_stable':
            return stable_reading(grays[ident], callback)
        if kind == 'size_stable_C':
            return size_stable_reading(grays[ident], callback)
        if kind == 'circle_strip_D-1':
            return circle_strip_reading(grays[ident], callback)
        return peeled_circle_strip_reading(peeled[ident], callback)

    def stage(name, targets, kind):
        folder = dest/name; inputs = folder/'inputs'; inputs.mkdir(parents=True)
        details, fresh, reused = {}, [], []
        for ident in targets:
            variants = []
            def capture(image):
                number = len(variants)
                path = inputs/f'{ident}-{number}.png'
                assert cv2.imwrite(str(path), image)
                value = dict(id=f'{ident}-{name}-{number}', input=str(path), input_sha256=sha(path), input_shape=list(image.shape))
                if kind == 'hull_stable': value['k'] = (2., 2.5, 3.)[number]
                elif kind != 'enclosure': value['pad_y'] = (16, 24)[number]
                variants.append(value)
                row = dict(original[ident], **{k: value[k] for k in ('id', 'input', 'input_sha256')}, physical_crop_id=ident)
                # Same-run C/24 may reuse its byte-identical B input, as in 166.
                prior = cache.get((ident, value['input_sha256'])) if kind == 'size_stable_C' else None
                if prior:
                    reused.append(dict(row, text=prior['text'], score=prior['score'], ocr_executed=True, reused_from=prior['input']))
                else: fresh.append(row)
                return '', 0.
            transform(ident, kind, capture)
            details[ident] = dict(method=kind, variants=variants)
        save(inputs/'regions.json', fresh)
        found = ocr(inputs, folder/'ocr') + reused
        by_id = {r['id']: r for r in found}
        for ident, detail in details.items():
            reads = [dict(v, text=by_id[v['id']]['text'], score=by_id[v['id']]['score']) for v in detail['variants']]
            iterator = iter(reads)
            def replay(image):
                r = next(iterator)
                assert np.array_equal(image, cv2.imread(r['input'], 0))
                return r['text'], r['score']
            result = transform(ident, kind, replay)
            stable = result is not None if kind != 'enclosure' else True
            detail.update(reads=reads, stable=stable,
                          selected=by_id[reads[1 if kind == 'hull_stable' else -1]['id']] if stable else None)
            for r in reads: cache[(ident, r['input_sha256'])] = r
        save(folder/'processed.json', details)
        phases[name] = dict(targets=len(targets), fresh=len(fresh), reused=len(reused), stable=sum(d['stable'] for d in details.values()))
        emit(stage='retry-'+name, done=len(pages), total=len(pages), message=name+' 재판독 단계가 끝났습니다.')
        return details

    def apply(details, *, confirmation=False):
        for ident, detail in details.items():
            parent = current[ident]
            if confirmation:
                trace = dict(parent['retry_search'], confirmation_reads=detail['reads'])
                extra = dict(original[ident], **{k: trace[k] for k in ('text', 'score', 'input', 'input_sha256')})
                updated = reconcile(parent, extra, trace, allow_low_confidence_consensus=True)
                updated['retry_search'] = updated.pop('circle_search')
            else:
                trace = dict(method=detail['method'], reads=detail['reads'], stable=detail['stable'], previous_retry=parent.get('retry_search'))
                if detail['stable']:
                    updated = reconcile(parent, detail['selected'], trace, allow_low_confidence_consensus=True)
                    updated['retry_search'] = updated.pop('circle_search')
                else:
                    last = detail['reads'][-1] if detail['reads'] else None
                    updated = dict(parent, retry_search=dict(trace, adopted=False, status='fixed_consensus_failed',
                        previous_text=parent['text'], previous_score=parent['score'],
                        **({k: last[k] for k in ('input', 'input_sha256', 'text', 'score')} if last else {})))
            current[ident] = updated

    peels = stage('peel', [i for i in eligible_ids if peeled[i] is not None], 'enclosure'); apply(peels)
    b = stage('B', [i for i in eligible_ids if peeled[i] is None], 'hull_stable'); apply(b)
    c = stage('C', [i for i, d in b.items() if not d['stable']], 'size_stable_C'); apply(c)
    d1 = stage('D1', [i for i, d in c.items() if not d['stable']], 'circle_strip_D-1'); apply(d1)
    d2_ids, confirm_ids = [], []
    for ident, detail in peels.items():
        selected = detail['selected']
        if to_digit(selected['text']) is None or selected['score'] < .8:
            d2_ids.append(ident)
        elif current[ident].get('reread_conflict') and to_digit(original[ident]['text']) is not None and original[ident]['score'] < .8:
            confirm_ids.append(ident)
    d2 = stage('D2', d2_ids + confirm_ids, 'circle_strip_D-2')
    apply({i: d2[i] for i in d2_ids})
    apply({i: d2[i] for i in confirm_ids}, confirmation=True)
    shared = dest/'shared-batch'; shared.mkdir()
    save(shared/'results.json', [current[r['id']] for r in original_rows])
    save(shared/'timing.json', read(dest/'ocr/timing.json'))
    assign(source, shared, dest/'assigned', None, minimum_overlap=.7, enclosing_candidates=True)
    # Display the final assigned zone, including the existing bottom extension.
    contexts = dest/'contexts'; contexts.mkdir()
    questions = read(dest/'assigned/questions.json')
    for page in read(source/'pages.json'):
        native = cv2.imdecode(np.fromfile(source/'sources'/Path(page['source']).name, np.uint8), 0)
        reference = cv2.imread(str(source/'pages'/f"{page['id']}-original.png"), 0)
        sy, sx = native.shape[0]/reference.shape[0], native.shape[1]/reference.shape[1]
        matrix = np.diag([sx, sy, 1]) @ np.array(page['matrix']) @ np.diag([1/sx, 1/sy, 1])
        high = cv2.warpPerspective(native, matrix, (native.shape[1], native.shape[0]), borderValue=255)
        for q in questions:
            if q['page'] != page['page']: continue
            l, t, r, btm = q['zone']; path = contexts/f"{q['id']}.jpg"
            assert cv2.imwrite(str(path), high[round(t*sy):round(btm*sy), round(l*sx):round(r*sx)])
            q['context'] = str(path)
    save(dest/'assigned/questions.json', questions)
    by_question = {q['id']: q for q in questions}
    evaluation = read(dest/'assigned/evaluation.json')
    for q in evaluation: q['context'] = by_question[q['id']]['context']
    save(dest/'assigned/evaluation.json', evaluation)
    from app import egw4_basegrade as adapter
    emit(stage='grading', done=0, total=len(pages), message='판독 근거를 채점 결과로 정리하고 있습니다.')
    adapter.grade(dest/'assigned', source, dest/'review', 'egw4-'+source.parent.name, COMMIT, '객관식 채점 결과')
    for name, digest in tracked.items(): assert sha(Path(name)) == digest, name
    for name, digest in engine_files.items(): assert sha(Path(name)) == digest, name
    save(dest/'execution.json', dict(commit=COMMIT, rule_changes=False,
        old_student_annotations=False, reviewed_transcription_used=False, pages=pages,
        initial_ocr=read(dest/'ocr/timing.json'), retries=phases, unchanged_inputs=tracked))
    emit(stage='grading', done=len(pages), total=len(pages), message='기본 채점이 끝났습니다.')


if __name__ == '__main__':
    main()
