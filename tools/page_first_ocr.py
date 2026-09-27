"""Detect page-wide ink, recognize once, then associate intact crops with questions."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from tools.extract_added_ink import choice_boxes, choice_preservation_mask, extract_added_ink


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def page_regions(aligned, original):
    """Existing B thresholds, applied to the whole page without question zones."""
    ink = cv2.adaptiveThreshold(aligned, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 14)
    printed = cv2.dilate(np.uint8(original < 195), np.ones((3, 3), np.uint8))
    _, labels, stats, _ = cv2.connectedComponentsWithStats(np.uint8((ink > 0) & (printed == 0)))
    clean = np.zeros_like(aligned)
    for ident, (_, _, _, height, area) in enumerate(stats[1:], 1):
        if area >= 8 and height >= 3:
            clean[labels == ident] = 255
    joined = cv2.morphologyEx(clean, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    _, _, stats, _ = cv2.connectedComponentsWithStats(joined)
    height, width = aligned.shape
    regions = []
    for x, y, w, h, area in stats[1:]:
        if area >= 35 and h >= 8 and w >= 3:
            regions.append(dict(ink_box=[int(x), int(y), int(x+w), int(y+h)],
                                box=[max(0, int(x)-4), max(0, int(y)-4), min(width, int(x+w)+4), min(height, int(y+h)+4)]))
    return sorted(regions, key=lambda r: (r['box'][1], r['box'][0], r['box'][3], r['box'][2]))


def associate(box, questions, minimum_overlap=None):
    """Geometry only: no OCR text, answer key, confidence or transcription input."""
    if minimum_overlap is not None and not .5 <= minimum_overlap <= 1:
        raise ValueError('Minimum overlap must be between 0.5 and 1')
    l, t, r, b = box
    if l >= r or t >= b:
        raise ValueError('Invalid ink box')
    hits = []
    for q in questions:
        a, c, d, e = q['zone']
        area = max(0, min(r, d)-max(l, a)) * max(0, min(b, e)-max(t, c))
        if area:
            hits.append(dict(question_id=q['id'], overlap_fraction=area/((r-l)*(b-t))))
    status = ('assigned' if len(hits) == 1 and hits[0]['overlap_fraction'] == 1 else
              'ambiguous' if len(hits) > 1 else 'outside_zone' if hits else 'unassigned')
    result = dict(status=status, candidates=hits)
    if minimum_overlap is not None:
        qualified = [hit for hit in hits if hit['overlap_fraction'] >= minimum_overlap]
        # A 50/50 split or overlapping zones never gets an arbitrary winner.
        if len(qualified) == 1:
            result = dict(status='assigned', candidates=qualified)
        result.update(minimum_overlap=minimum_overlap, intersections=hits)
    return result


def prepare(source, output, selected_pages):
    if output.exists():
        raise ValueError('Use a fresh output folder')
    pages = [p for p in read(source/'pages.json') if p['page'] in selected_pages]
    if {p['page'] for p in pages} != set(selected_pages):
        raise ValueError('Requested page missing')
    if any(not p.get('matrix') or p['inliers'] <= 30 or not np.isfinite(p['median_error']) or p['median_error'] > 3 for p in pages):
        raise ValueError('Alignment requires review')
    choices = choice_boxes(source, {p['id']: p for p in pages})
    output.mkdir(parents=True); (output/'raw').mkdir(); (output/'crops').mkdir()
    rows = []; hashes = {}
    for p in pages:
        original_path = source/'pages'/f"{p['id']}-original.png"
        scan = source/'sources'/Path(p['source']).name
        hashes[str(scan.resolve())] = sha(scan); hashes[str(original_path.resolve())] = sha(original_path)
        original = cv2.imread(str(original_path), 0)
        native = cv2.imdecode(np.fromfile(str(scan), np.uint8), 0)
        if native is None or original is None:
            raise ValueError('Image could not be read')
        h,w = original.shape; sy,sx = native.shape[0]/h,native.shape[1]/w
        matrix = np.array(p['matrix'])
        aligned = cv2.warpPerspective(cv2.resize(native, (w,h)), matrix, (w,h), borderValue=255)
        high = cv2.warpPerspective(native, np.diag([sx,sy,1])@matrix@np.diag([1/sx,1/sy,1]), (native.shape[1],native.shape[0]), borderValue=255)
        for number, region in enumerate(page_regions(aligned, original), 1):
            ident=f"{p['id']}-ink{number:04}"
            l,t,r,b=region['box']; student=high[round(t*sy):round(b*sy),round(l*sx):round(r*sx)]
            reference=cv2.resize(original[t:b,l:r], (student.shape[1],student.shape[0]))
            preserve, selected=choice_preservation_mask(student.shape, region['box'], choices[p['id']])
            extracted, evidence=extract_added_ink(student,reference,preserve)
            raw=output/'raw'/f'{ident}.png'; dest=output/'crops'/f'{ident}.png'
            for path,image in [(raw,student),(dest,extracted)]:
                if not cv2.imwrite(str(path),cv2.copyMakeBorder(image,10,10,10,10,cv2.BORDER_CONSTANT,value=255)):
                    raise OSError(f'Cannot save {path}')
            rows.append(dict(id=ident,page=p['page'],page_id=p['id'],**region,
                             input=str(dest.resolve()),input_sha256=sha(dest),source_input=str(raw.resolve()),source_input_sha256=sha(raw),
                             reference_page=str(original_path.resolve()),reference_evidence=evidence,
                             empty=not bool(np.any(extracted < 255)),preserved_choices=selected,requires_choice_mark_review=bool(selected)))
    assert all('question_id' not in r for r in rows)
    save(output/'regions.json',rows)
    save(output/'provenance.json',dict(order=['whole_page_ink','OCR','question_zones','association'],pages=selected_pages,
                                     question_zones_used_for_extraction=False,source_hashes=hashes,regions=len(rows)))
    print(json.dumps(dict(pages=selected_pages,regions=len(rows),question_assignment=False)),flush=True)


def extend_column_bottoms(questions, page_heights):
    """Extend only the spatially last question in each existing column."""
    columns = {}
    for q in questions:
        l, t, r, b = q['zone']
        height = page_heights[(q['set'], q['page'])]
        if not 0 <= t < b <= height or l >= r:
            raise ValueError('Question zone outside page or invalid')
        columns.setdefault((q['set'], q['page'], l, r), []).append(q)
    for group in columns.values():
        bottom = max(q['zone'][1] for q in group)
        last = [q for q in group if q['zone'][1] == bottom]
        if len(last) != 1:
            raise ValueError('Column has no unique last question')
        q = last[0]
        q['zone_before_bottom_extension'] = list(q['zone'])
        q['zone'] = [*q['zone'][:3], page_heights[(q['set'], q['page'])]]


def assign(source, recognized, output, annotations=None, minimum_overlap=None):
    if output.exists():
        raise ValueError('Use a fresh association output')
    raw = read(recognized/'results.json')
    if len({r['id'] for r in raw}) != len(raw) or any('question_id' in r for r in raw):
        raise ValueError('Expected unique, unassigned page OCR results')
    for r in raw:
        if not {'text','score','ocr_executed'} <= r.keys() or sha(Path(r['input'])) != r['input_sha256']:
            raise ValueError('Recognition missing or evidence changed')
    # Load question zones only after the page OCR results are complete.
    timing = read(recognized/'timing.json')
    scope = read(Path(timing['inputs'])/'provenance.json')['pages']
    if not {r['page'] for r in raw} <= set(scope):
        raise ValueError('OCR page scope mismatch')
    questions = [q for q in read(source/'questions.json') if q['page'] in scope]
    heights = {}
    for page in read(source/'pages.json'):
        if page['page'] in scope:
            image = cv2.imread(str(source/'pages'/f"{page['id']}-original.png"), 0)
            if image is None:
                raise ValueError('Page image required for bottom boundary')
            heights[(page['id'].rsplit('-', 1)[0], page['page'])] = image.shape[0]
    extend_column_bottoms(questions, heights)
    notes = [r for r in read(annotations) if r.get('semantic_annotation')] if annotations else []
    all_questions = {q['id']:q for q in read(source/'questions.json')}
    output.mkdir(parents=True); results=[]; associations=[]; unassigned=[]
    for q in questions:
        q['segments']=[]
    by_id={q['id']:q for q in questions}
    for r in raw:
        association=associate(r['ink_box'],[q for q in questions if q['page']==r['page']],minimum_overlap)
        associations.append(dict(crop_id=r['id'],box=r['box'],ink_box=r['ink_box'],**association))
        if not association['candidates']:
            unassigned.append(r)
        for hit in association['candidates']:
            q=by_id[hit['question_id']];ident=f"{q['id']}-page-{r['id']}"
            row=dict(r,id=ident,question_id=q['id'],page_crop_id=r['id'],ownership=association,
                     ownership_review=association['status']!='assigned')
            for note in notes:
                if all_questions[note['question_id']]['page'] != r['page']:
                    continue
                a,c,d,e=note['box'];l,t,rr,b=r['box']
                if max(a,l)<min(d,rr) and max(c,t)<min(e,b):
                    row['semantic_annotation']=note['semantic_annotation'] if note['source_input_sha256']==r['source_input_sha256'] else dict(meaning='previous_annotation_overlap_requires_review',source_crop_id=note['id'])
            results.append(row);q['segments'].append(ident)
    evaluation=[dict(id=q['id'],page=q['page'],selection=None,key_answer=q['key']['answer'],status='보류',candidates=[],context=q['context']) for q in questions]
    save(output/'results.json',results);save(output/'evaluation.json',evaluation)
    save(output/'associations.json',associations);save(output/'unassigned.json',unassigned)
    save(output/'questions.json',questions)
    save(output/'provenance.json',dict(method='145 page-wide recognition before question association; no OCR text/key used for ownership',
                                      fresh_result_sha256=sha(recognized/'results.json'),page_crop_count=len(raw),assigned_links=len(results),
                                      unassigned=len(unassigned),ambiguous=sum(a['status']!='assigned' for a in associations),
                                      source_ocr=str((recognized/'results.json').resolve()),minimum_overlap=minimum_overlap,
                                      bottom_boundary='last question in each column extends to page bottom',
                                      overlap_basis='ink bounding rectangle before crop padding'))
    print(json.dumps(dict(crops=len(raw),links=len(results),unassigned=len(unassigned),questions=len(questions))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();commands=parser.add_subparsers(dest='command',required=True)
    prep=commands.add_parser('prepare');prep.add_argument('source',type=Path);prep.add_argument('output',type=Path);prep.add_argument('--pages',type=int,nargs='+',required=True)
    assigner=commands.add_parser('assign');assigner.add_argument('source',type=Path);assigner.add_argument('recognized',type=Path);assigner.add_argument('output',type=Path);assigner.add_argument('--annotations',type=Path)
    assigner.add_argument('--minimum-overlap',type=float)
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.source,args.output,args.pages)
    else:assign(args.source,args.recognized,args.output,args.annotations,args.minimum_overlap)
