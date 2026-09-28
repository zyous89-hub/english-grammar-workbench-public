"""Confirm held answers using independent handwriting and frozen choice marks."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import math
from pathlib import Path
import shutil
import uuid

import cv2
import numpy as np
from PIL import Image

from src.result_files import image_path, load_result, write_result
from tools.choice_mark_recommendations import PARAMETERS, recommend
from tools.classify_grid_stages import REASONS, overlaps, question_review, student_choices
from tools.page_first_ocr import read, save, sha
from tools.scan_resolution import inspect_scan_sizes
from tools.ocr_retry_preprocess import _holes
from tools.compare_f08_circles import circles

MINIMUM_SCORE = .5


def current_input(record):
    for name in ('retry_search','circle_search'):
        trace = record.get(name) or {}
        if trace.get('adopted') and (trace.get('text'),trace.get('score')) == (record.get('text'),record.get('score')):
            return trace['input']
    return record.get('input')


def numeric_readings(record):
    """Original and all stored retry readings; no OCR or confidence rewriting."""
    for text_key, score_key in (('text','score'), ('previous_text','previous_score'),
                                ('original_text','original_score')):
        text, score = record.get(text_key, ''), record.get(score_key)
        values = student_choices(text or '')
        if values and score is not None and math.isfinite(score) and score >= MINIMUM_SCORE:
            yield dict(values=values, text=text, score=score,
                       input=current_input(record) if text_key=='text' else None)
    for name in ('retry_search', 'circle_search', 'previous_retry'):
        if record.get(name):
            yield from numeric_readings(record[name])
    for name in ('reads', 'prior_size_reads', 'confirmation_reads'):
        for reading in record.get(name, []):
            yield from numeric_readings(reading)


def closed_border(blocker, candidate, gray):
    """Prove an intact frame contains only the separate answer crop's ink."""
    if gray is None or gray.ndim != 2 or not gray.size or blocker['id'] == candidate['id']:
        return False
    x,y,X,Y = blocker['box']; a,b,A,B = candidate.get('ink_box', candidate['box'])
    if not (x < a < A < X and y < b < B < Y):
        return False
    h,w = gray.shape
    yy,xx = np.indices(gray.shape)
    inside = ((xx >= (a-x)*w/(X-x)) & (xx < (A-x)*w/(X-x))
              & (yy >= (b-y)*h/(Y-y)) & (yy < (B-y)*h/(Y-y)))
    ink = np.uint8(gray < 195)
    count, labels = cv2.connectedComponents(ink, connectivity=8)
    for i in range(1, count):
        frame = np.uint8(labels == i)*255
        hole = _holes(frame)
        if not inside.any() or not np.all(hole[inside]):
            continue
        content = hole & (ink > 0)
        # The culprit crop must contain only this frame and the answer ink.
        if content.sum() < 8 or np.any((ink > 0) & ~inside & (labels != i)):
            continue
        # No fitted/closed/hull-filled gaps: the original ink must form the hole.
        contours, _ = cv2.findContours(frame, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        outline = max(contours, key=cv2.contourArea)
        polygon = cv2.approxPolyDP(outline, .025*cv2.arcLength(outline, True), True)
        if (len(polygon)==4 and cv2.isContourConvex(polygon)) or circles(255-frame):
            return True
    return False


def decide(question, review, regions, raw, marks, printed, alignment, exemptions=(), expected_count=None,
           border_images=None):
    """Clear only traced same-answer causes; retain all other held reasons."""
    audit = dict(applied=False, excluded=[], readings=[], reason_audit=[], decision='already_automatic')
    if review['selection'] is not None:
        return review, audit
    if not review['key'] or len(review['key']) != 1:
        audit['decision'] = 'no_single_mark_or_single_key'
        return review, audit
    if sorted(m['symbol'] for m in printed) != list('①②③④⑤'):
        audit['decision'] = 'printed_numbers_incomplete'
        return review, audit
    mark = recommend(question, marks)
    accepted = [r for r in regions if r['stage']==0 and r['score'] >= .8
                and not any(overlaps(r['box'], m['box']) for m in printed)]
    if mark is None and not (accepted and review['proposed_selection'] and len(review['proposed_selection'])==1):
        audit['decision'] = 'no_single_mark_or_single_key'
        return review, audit
    number = '①②③④⑤'.index(mark['symbol'])+1 if mark else review['proposed_selection'][0]
    audit['mark'] = number
    audit['has_choice_mark'] = mark is not None
    for r in regions:
        hits = [m['symbol'] for m in printed if overlaps(r['box'], m['box'])]
        if hits:
            audit['excluded'].append(dict(id=r['id'], printed=hits))
            continue
        if r['stage']==1 or r.get('ownership_review') or r.get('semantic_annotation'):
            continue
        for reading in numeric_readings(raw[r['id']]):
            audit['readings'].append(dict(reading, crop_id=r['id']))
    readings = audit['readings']
    if not readings:
        audit['decision'] = 'no_independent_digit'
        return review, audit
    best = max(readings, key=lambda r:r['score'])
    audit['best'] = best
    if best['values'] != [number] or any(r['values'] != [number] for r in readings):
        audit['decision'] = 'independent_digits_disagree'
        return review, audit
    candidate = next(r for r in regions if r['id']==best['crop_id'])
    updated = deepcopy(regions)
    if best['score'] < .8:
        if mark is None:
            audit['decision'] = 'no_single_mark_or_single_key'
            return review, audit
        promoted = next(r for r in updated if r['id']==candidate['id'])
        promoted.update(stage=0, reason='candidate', choice=[number])
        audit['path'] = 'low_confidence_agreement'
    else:
        # Existing >=.8 candidates only: this path removes a duplicate check's
        # F08(b), and never adopts a high retry that failed the existing rules.
        eligible = [r for r in regions if r['stage']==0 and r['choice']==[number]
                    and r['id'] in {x['crop_id'] for x in readings}]
        if not eligible or review['proposed_selection'] != [number]:
            audit['decision'] = 'high_retry_not_adopted'
            return review, audit
        candidate = max(eligible, key=lambda r:r['score'])
        best = dict(values=[number], text=candidate['text'], score=candidate['score'],
                    crop_id=candidate['id'], input=current_input(raw[candidate['id']]))
        audit['path'] = 'existing_candidate_mark_blocker'
    audit['handwriting'] = best
    chosen = [m['box'] for m in printed if m['symbol']=='①②③④⑤'[number-1]]
    by_id = {r['id']:r for r in regions}

    def trace(reason, phase):
        allowed = (reason['rule']=='F08(b)' and reason['code']=='6'
                   or reason['rule']=='no_candidate' and reason['code'] in ('2','8'))
        causes = []
        for ident in reason['crop_ids']:
            r = by_id.get(ident); method = None
            if allowed and r is not None and r['reason']==reason['code']:
                if len(chosen)==1 and overlaps(r['box'], chosen[0]) and (
                        reason['code']!='2' or r.get('empty') is True):
                    method = 'same_printed_number'
                elif reason['rule']=='F08(b)' and closed_border(r, raw[candidate['id']],
                        (border_images or {}).get(ident)):
                    method = 'closed_border_only_answer'
            causes.append(dict(crop_id=ident, method=method, cleared=bool(method)))
        clear = bool(causes) and all(c['cleared'] for c in causes)
        audit['reason_audit'].append(dict(phase=phase, rule=reason['rule'], code=reason['code'],
                                         causes=causes, cleared=clear))
        return clear

    # Promotion can make no_candidate reasons disappear. Preserve every protected
    # original reason unless ALL of its recorded causes satisfy the new rule.
    blocked = []; cleared_original = []
    for reason in review['reasons']:
        clear = trace(reason, 'original')
        if clear:
            cleared_original.append(reason)
        elif not (reason['rule']=='no_candidate' and reason['code'] in ('5','6','9')
                  or reason['rule']=='F08(b)' and reason['code']=='6'):
            blocked.append(reason)
    trial = question_review(updated, question['answer_key'], alignment,
                            f08_exemptions=exemptions, expected_count=expected_count)
    f08_exemptions = set(exemptions)
    for reason in trial['reasons']:
        if trace(reason, 'candidate') and reason['rule']=='F08(b)':
            f08_exemptions.update(reason['crop_ids'])
    changed = question_review(updated, question['answer_key'], alignment,
                              f08_exemptions=f08_exemptions, expected_count=expected_count)
    remaining = blocked + [r for r in changed['reasons'] if r not in blocked]
    audit.update(mark_exemptions=sorted(f08_exemptions-set(exemptions)), remaining_reasons=remaining)
    if remaining:
        audit['decision'] = 'protected_hold' if blocked else 'remaining_hold'
        audit['blockers'] = blocked
        if cleared_original and any(r not in cleared_original for r in review['reasons']):
            held = deepcopy(review)
            held['reasons'] = [r for r in review['reasons'] if r not in cleared_original]
            held['stage'] = max((r['stage'] for r in held['reasons'] if r['stage'] is not None), default=None)
            audit['reasons_changed'] = True
            return held, audit
        return review, audit
    if changed['selection'] != [number]:
        raise ValueError('Same-answer candidate was not reproduced')
    audit.update(applied=True, decision='confirmed')
    return changed, audit


def page_boxes(marks, zone, scan_size, reference_size):
    """Invert the existing rounded 300dpi context crop, without image alignment."""
    sx, sy = (a/b for a,b in zip(scan_size,reference_size))
    ox, oy = round(zone[0]*sx), round(zone[1]*sy)
    return [dict(symbol=m['symbol'], box=[(m['box'][0]+ox)/sx,(m['box'][1]+oy)/sy,
                 (m['box'][2]+ox)/sx,(m['box'][3]+oy)/sy]) for m in marks]


def run(baseline, trial, source, measurements_path, output):
    if output.exists():
        raise FileExistsError(output)
    tracked = {}

    def tracked_read(path):
        tracked[str(path.resolve())] = sha(path)
        return read(path)

    measurements = tracked_read(measurements_path)
    if measurements['parameters'] != PARAMETERS:
        raise ValueError('Use the unchanged 5453482 choice-mark measurements')
    classified = tracked_read(trial/'baseline/classification.json')['runs']
    if len(classified)!=1:
        raise ValueError('One classified batch required')
    regions = classified[0]['regions']
    raw_rows = tracked_read(trial/'assigned/results.json')
    raw = {r['id']:r for r in raw_rows}
    if len(raw)!=len(raw_rows) or set(raw)!={r['id'] for r in regions}:
        raise ValueError('OCR and classification region coverage differs')
    questions = {q['id']:q for q in tracked_read(source/'questions.json')}
    pages = inspect_scan_sizes(tracked_read(source/'pages.json'),source)
    alignments = {p['page']:p for p in pages}
    dimensions = {}
    for p in pages:
        paths = [source/'sources'/Path(p['source']).name,source/'pages'/f"{p['id']}-original.png"]
        for path in paths:
            tracked[str(path.resolve())] = sha(path)
        with Image.open(paths[0]) as scan, Image.open(paths[1]) as reference:
            dimensions[(p['id'].rsplit('-',1)[0],p['page'])] = (scan.size,reference.size)
    mapped = {}
    for qid, context in measurements['contexts'].items():
        q = questions[qid]; path = Path(q['context'])
        tracked[str(path.resolve())] = sha(path)
        if tracked[str(path.resolve())]!=context['sha256']:
            raise ValueError('Context measurement differs from the original source question')
        sizes = dimensions[(q['set'],q['page'])]
        sx,sy = (a/b for a,b in zip(*sizes))
        l,t,r,b = q['zone']
        expected = [round(r*sx)-round(l*sx),round(b*sy)-round(t*sy)]
        if context['size']!=expected:
            raise ValueError('Expected the original 300dpi context crop')
        mapped[qid] = page_boxes(measurements['questions'][qid],q['zone'],*sizes)
    output.mkdir(parents=True)
    audits = {}
    for mode in ('duplicate','broad'):
        result_path = baseline/mode/'result.json'
        tracked[str(result_path.resolve())] = sha(result_path)
        original = load_result(result_path)
        comparisons = tracked_read(trial/'comparison'/f'{mode}.json')['rows']
        rows = {q['id']:q for q in comparisons}
        if {q['id'] for q in original['questions']} != set(rows) or not set(rows)<=mapped.keys():
            raise ValueError('Result, comparison and measurement coverage differs')
        dest = output/mode; dest.mkdir()
        result = deepcopy(original); audit = []
        for q in result['questions']:
            row = rows[q['id']]; before = row['review']
            assigned = [r for r in regions if r['question']==q['id']]
            alignment = alignments[row['page']]
            reproduced = question_review(assigned,q['answer_key'],alignment,
                f08_exemptions=row['exemptions'],expected_count=row.get('required_count'))
            reasons = [dict(code=r['code'],stage=r['stage'],message=r.get('message') or REASONS[r['code']])
                       for r in before['reasons']]
            if before!=reproduced or q['reasons']!=reasons or q['review_stage']!=(before['stage'] or None) or q['judgement']!=before['status'] or q['read_answer']!=(
                ','.join(map(str,before['proposed_selection'])) if before['proposed_selection'] is not None else None):
                raise ValueError('Frozen grading result does not reproduce')
            border_images = {}
            if before['selection'] is None:
                for r in assigned:
                    if r['reason']!='6' or not any(
                            r['box'][0]<a<A<r['box'][2] and r['box'][1]<b<B<r['box'][3]
                            for c in assigned if c['id']!=r['id']
                            for a,b,A,B in [raw[c['id']].get('ink_box', c['box'])]):
                        continue
                    path = Path(raw[r['id']]['input'])
                    tracked[str(path.resolve())] = sha(path)
                    if tracked[str(path.resolve())] != raw[r['id']]['input_sha256']:
                        raise ValueError('Original border image changed')
                    with Image.open(path) as image:
                        gray = np.array(image.convert('L'))
                    sq = questions[q['id']]
                    sx,sy = (a/b for a,b in zip(*dimensions[(sq['set'],sq['page'])]))
                    l,t,right,bottom = r['box']
                    expected_shape = (round(bottom*sy)-round(t*sy)+20,round(right*sx)-round(l*sx)+20)
                    if gray.shape != expected_shape:
                        raise ValueError('Expected the original padded crop')
                    border_images[r['id']] = gray[10:-10,10:-10]
            after, evidence = decide(q,before,assigned,raw,measurements['questions'][q['id']],
                mapped[q['id']],alignment,row['exemptions'],row.get('required_count'),border_images)
            audit.append(dict(id=q['id'],before=before,after=after,**evidence))
            for e in q['evidence_images']:
                path = image_path(result_path.parent,e['path'])
                tracked[str(path)] = sha(path)
                target = image_path(dest,e['path']); target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(path,target)
            if not evidence['applied']:
                if evidence.get('reasons_changed'):
                    q.update(reasons=[dict(code=r['code'],stage=r['stage'],message=r.get('message') or REASONS[r['code']])
                                      for r in after['reasons']], review_stage=after['stage'],
                             rules_version=q['rules_version']+' + same-answer-causes-v1')
                continue
            reading = evidence['handwriting']; number = evidence['mark']
            label = (f"두 증거 일치 · 손글씨 {number} {reading['score']:.2f} + 선택 표시 {number}"
                     if evidence['has_choice_mark'] else f"같은 답 표시 사유 해소 · 손글씨 {number} {reading['score']:.2f}")
            handwriting = Path(reading['input'] or raw[reading['crop_id']]['input'])
            images = [('two-evidence-handwriting' if evidence['has_choice_mark'] else 'same-answer-handwriting',handwriting)]
            if evidence['has_choice_mark']:
                mark = next(m for m in measurements['questions'][q['id']] if m['symbol']=='①②③④⑤'[number-1])
                mark_path = image_path(measurements_path.parent,mark['image'])
                if sha(mark_path)!=mark['image_sha256']:
                    raise ValueError('Choice-mark image changed')
                images.append(('two-evidence-mark',mark_path))
            for ident,path in images:
                digest=sha(path); tracked[str(path.resolve())]=digest
                relative=f'evidence/{digest}{path.suffix.lower()}'
                shutil.copyfile(path,image_path(dest,relative))
                q['evidence_images'].append(dict(id=ident,label=label,path=relative))
            additional = (not evidence['has_choice_mark'] or any(a['cleared'] and (
                a['code'] in ('2','8') or any(c['method']=='closed_border_only_answer' for c in a['causes']))
                for a in evidence['reason_audit']))
            q.update(read_answer=str(number),judgement=after['status'],review_stage=None,reasons=[],
                     rules_version=q['rules_version']+' + two-evidence-v1'+(' + same-answer-causes-v1' if additional else ''))
        result.update(result_id=str(uuid.uuid4()),generated_at=datetime.now(timezone.utc).isoformat())
        write_result(dest/'result.json',result)
        corrections=result_path.parent/'teacher-corrections.json'
        if corrections.exists():
            tracked[str(corrections.resolve())]=sha(corrections)
            shutil.copyfile(corrections,dest/corrections.name)
        audits[mode]=audit
    for path,digest in tracked.items():
        if sha(Path(path))!=digest:
            raise ValueError(f'Input changed: {path}')
    save(output/'dual-evidence.json',dict(minimum_score=MINIMUM_SCORE,policies=audits,source_hashes=tracked))
    return {mode:[q['id'] for q in audit if q['applied']] for mode,audit in audits.items()}


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('baseline','trial','source','measurements','output'):
        parser.add_argument(name,type=Path)
    args=parser.parse_args()
    print(run(args.baseline,args.trial,args.source,args.measurements,args.output))
