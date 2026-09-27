"""158 experiment: one retry per physical crop; no key/transcription selection."""
import argparse
from collections import Counter
from pathlib import Path
import subprocess
import sys
import tempfile

import cv2
import numpy as np

from tools.answer_count_search import has_retry_history
from tools.circle_inner_search import enclosures, reconcile as reconcile_shape
from tools.extract_added_ink import choice_boxes, choice_preservation_mask, extract_added_ink
from tools.page_first_ocr import associate, read, save, sha


def size_image(gray, grading_height, minimum=8, height=40, padding=24):
    ys, xs = np.where(gray < 255)
    if not len(xs):
        return None, 0.0
    ink_height = int(ys.max()-ys.min()+1) * grading_height / gray.shape[0]
    if ink_height <= minimum:
        return None, ink_height
    tight = gray[ys.min():ys.max()+1, xs.min():xs.max()+1]
    width = max(1, round(tight.shape[1]*height/tight.shape[0]))
    resized = cv2.resize(tight, (width, height), interpolation=cv2.INTER_NEAREST)
    return cv2.copyMakeBorder(resized, padding, padding, padding, padding,
                              cv2.BORDER_CONSTANT, value=255), ink_height


def connected_frame(student, extracted, seed_box, tolerance=20):
    """Experimental brightness/shade connection; allows touching inside strokes."""
    x,y,X,Y = seed_box
    residual = extracted < 255
    seed = np.zeros_like(residual); seed[y:Y,x:X] = residual[y:Y,x:X]
    if not seed.any():
        return None, dict(status='no_seed')
    background = cv2.morphologyEx(student, cv2.MORPH_CLOSE, np.ones((15,15),np.uint8))
    shade = background.astype(float)-student
    brightness = float(np.median(student[seed])); contrast = float(np.median(shade[seed]))
    similar = residual & (np.abs(student.astype(float)-brightness) <= tolerance) & (np.abs(shade-contrast) <= tolerance)
    # ponytail: only directly connected pixels; gap reconstruction is a later experiment.
    _, labels = cv2.connectedComponents(np.uint8(similar | seed), connectivity=8)
    connected = np.isin(labels, np.unique(labels[seed])) & (labels > 0)
    frame_image = np.where(connected, extracted, 255).astype(np.uint8)
    frames = enclosures(frame_image)
    if not frames:
        return None, dict(status='no_connected_enclosure', brightness=brightness, contrast=contrast)
    # Keep all detected interiors (including disconnected letters); do not choose by OCR score.
    interiors = np.logical_or.reduce([inside for inside, _, _ in frames])
    boundaries = np.logical_or.reduce([boundary for _, boundary, _ in frames])
    keep = interiors & ~boundaries & residual
    if not keep.any():
        return None, dict(status='empty_interior')
    return np.where(keep, extracted, 255).astype(np.uint8), dict(
        status='frame_removed', brightness=brightness, contrast=contrast,
        shapes=[geometry for _, _, geometry in frames], retained_pixels=int(keep.sum()))


def reconcile(row, extra, trace):
    merged = reconcile_shape(row, extra, trace)
    merged['retry_search'] = merged.pop('circle_search')
    return merged


def run(batch, source, candidates, output, model, tolerance=20, prepare_only=False):
    if output.exists():
        raise ValueError('Use a fresh output directory; no restart of consumed retries')
    if not 0 <= tolerance <= 255:
        raise ValueError('Brightness tolerance must be within 0..255')
    audit = read(candidates); rows = read(batch/'results.json')
    if sha(batch/'results.json') != audit['source_hashes']['shared-batch/results.json']:
        raise ValueError('Candidate manifest is stale')
    by_id = {r['id']:r for r in rows}
    if len(by_id) != len(rows):
        raise ValueError('Duplicate physical crop IDs')
    selected = [r for r in audit['crops'] if not r['any_history'] and
                (r['broad']['candidate'] or r['duplicate']['candidate'])]
    for flag in selected:
        row = by_id[flag['id']]
        if has_retry_history(row) or row['route'] != 'student_candidate' or row['empty'] or row['answer_excluded']:
            raise ValueError('Candidate has retry history or an excluded route')
    tracked = {str(p.resolve()):sha(p) for p in (batch/'results.json', candidates, source/'pages.json',
               batch.parent/'assigned/questions.json', batch.parent/'assigned/associations.json', Path(__file__))}
    pages = {p['id']:p for p in read(source/'pages.json')}
    line_pages = {by_id[f['id']]['page_id'] for f in selected if f['line']}
    full_choices = choice_boxes(source, {p:pages[p] for p in line_pages})
    for page_id in line_pages:
        pdf=source/'sources'/f"{page_id.rsplit('-',1)[0]}-original.pdf"
        tracked[str(pdf.resolve())]=sha(pdf)
    questions = read(batch.parent/'assigned/questions.json')
    previous_owners = {a['crop_id']:a for a in read(batch.parent/'assigned/associations.json')}
    output.mkdir(parents=True); inputs=output/'inputs'; inputs.mkdir()
    prepared=[]; traces={}; cache={}
    for flag in selected:
        row=by_id[flag['id']]; ident=row['id']; page=pages[row['page_id']]
        if not page.get('matrix') or page['inliers']<=30 or not np.isfinite(page['median_error']) or page['median_error']>3:
            raise ValueError('Alignment requires review')
        original=Path(row['input'])
        if sha(original)!=row['input_sha256']:
            raise ValueError('Original crop changed')
        tracked[str(original.resolve())]=sha(original)
        gray=cv2.imread(str(original),0)[10:-10,10:-10]
        l,t,r,b=row['box']; trace=dict(method='resize', attempts=0, status='prepared', grading_height=b-t)
        target=gray; target_height=b-t
        if flag['line']:
            if row['page_id'] not in cache:
                reference_path=source/'pages'/f"{row['page_id']}-original.png"
                scan=source/'sources'/Path(page['source']).name
                for p in (reference_path,scan):tracked[str(p.resolve())]=sha(p)
                reference=cv2.imread(str(reference_path),0)
                native=cv2.imdecode(np.fromfile(str(scan),np.uint8),0)
                h,w=reference.shape; sy,sx=native.shape[0]/h,native.shape[1]/w
                matrix=np.diag([sx,sy,1])@np.array(page['matrix'])@np.diag([1/sx,1/sy,1])
                high=cv2.warpPerspective(native,matrix,(native.shape[1],native.shape[0]),borderValue=255)
                # Expansion can reach labels absent from every previous crop.
                cache[row['page_id']]=(reference,high,sx,sy,full_choices[row['page_id']])
            reference,high,sx,sy,choices=cache[row['page_id']]
            L,T,R,B=max(0,l-20),max(0,t-20),min(reference.shape[1],r+20),min(reference.shape[0],b+20)
            x,y,X,Y=round(L*sx),round(T*sy),round(R*sx),round(B*sy)
            student=high[y:Y,x:X]
            ref=cv2.resize(reference[T:B,L:R],(student.shape[1],student.shape[0]))
            preserve,labels=choice_preservation_mask(student.shape,[L,T,R,B],choices)
            extracted,_=extract_added_ink(student,ref,preserve)
            # Intermediate PNG is consumed locally and automatically removed; final evidence stays.
            with tempfile.TemporaryDirectory(prefix='ocr-line158-') as tmp:
                temp=Path(tmp)/'expanded.png'
                if not cv2.imwrite(str(temp),extracted):raise OSError('Could not write intermediate PNG')
                expanded=cv2.imread(str(temp),0)
            seed=[round(l*sx)-x,round(t*sy)-y,round(r*sx)-x,round(b*sy)-y]
            inside,line_trace=connected_frame(student,expanded,seed,tolerance)
            trace.update(line=line_trace, expanded_box=[L,T,R,B], brightness_tolerance=tolerance,
                         shade_tolerance=tolerance, protected_choices=labels)
            proof=inputs/(ident+'-expanded.png');cv2.imwrite(str(proof),expanded)
            trace['expanded_input']=str(proof.resolve())
            if inside is not None and not labels:
                target=inside;target_height=B-T;trace['method']='line_inner_resize'
                yy,xx=np.where(inside<255)
                support=[L+float(xx.min())/sx,T+float(yy.min())/sy,L+float(xx.max()+1)/sx,T+float(yy.max()+1)/sy]
                owners=associate(support,[q for q in questions if q['page']==row['page']],.7)
                old=previous_owners[ident]
                trace['support_box']=support
                trace['ownership_review']=(owners['status']!='assigned' or
                    {c['question_id'] for c in owners['candidates']}!={c['question_id'] for c in old['candidates']})
            else:
                trace['method']='line_resize_fallback'
                if labels:trace['line']['status']='protected_print_in_expansion'
        elif flag['zero'] or flag['shape']:
            frames=enclosures(gray)
            if frames:
                inside=np.logical_or.reduce([i for i,_,_ in frames])
                target=np.where(inside,gray,255).astype(np.uint8);trace['method']='shape_inner_resize'
        image,height=size_image(target,target_height,minimum=0 if trace['method']!='resize' else 8)
        trace['ink_height']=height
        if image is None:
            trace['status']='no_remaining_ink';traces[ident]=trace;continue
        dest=inputs/(ident+'.png')
        if not cv2.imwrite(str(dest),image):raise OSError('Could not write retry input')
        prepared.append(dict(row,input=str(dest.resolve()),input_sha256=sha(dest)))
        traces[ident]=trace
    save(inputs/'regions.json',prepared)
    save(output/'plan.json',dict(eligible=len(selected),extra_inputs=len(prepared),crops=traces,
         max_passes=1,history='any recorded search, including zero OCR attempts',
         transform='ink height40, white padding24; line expansion20 grading pixels',source_hashes=tracked))
    print(dict(eligible=len(selected),prepared=len(prepared),methods=dict(Counter(t['method'] for t in traces.values()))),flush=True)
    if prepare_only:
        return  # Input verification only, never starts or repeats OCR.
    if prepared:
        subprocess.run([sys.executable,'-m','tools.run_added_ink_ocr',str(inputs),str(source),str(output/'extra-ocr'),str(model)],check=True)
        extra={r['id']:r for r in read(output/'extra-ocr/results.json')}
        if set(extra)!={r['id'] for r in prepared} or not all(r['ocr_executed'] for r in extra.values()):
            raise ValueError('OCR coverage differs from prepared candidates')
    else:extra={}
    combined=[]
    for row in rows:
        ident=row['id']
        changed=reconcile(row,extra[ident],traces[ident]) if ident in extra else dict(row,retry_search=traces[ident]) if ident in traces else row
        if traces.get(ident,{}).get('ownership_review'):changed['retry_ownership_review']=True
        combined.append(changed)
    shared=output/'shared-batch';shared.mkdir();save(shared/'results.json',combined)
    save(shared/'timing.json',read(batch/'timing.json'))
    save(shared/'provenance.json',dict(parent_result_sha256=sha(batch/'results.json'),
         fresh_result_sha256=sha(shared/'results.json'),source_hashes=tracked,method='158 one retry, strict history exclusion'))
    for p,digest in tracked.items():
        if sha(Path(p))!=digest:raise ValueError('Source changed during execution')
    summary=dict(eligible=len(selected),additional_ocr=len(extra),
                 adopted=sum(r.get('retry_search',{}).get('adopted',False) for r in combined),
                 conflicts=sum(r.get('retry_search',{}).get('status')=='answer_conflict' for r in combined),
                 methods=dict(Counter(t['method'] for t in traces.values())))
    save(output/'summary.json',summary);print(summary,flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('batch','source','candidates','output','model'):parser.add_argument(name,type=Path)
    parser.add_argument('--tolerance',type=float,default=20)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args();run(args.batch,args.source,args.candidates,args.output,args.model,args.tolerance,args.prepare_only)
