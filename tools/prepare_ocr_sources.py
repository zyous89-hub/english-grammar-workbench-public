"""Source preparation with explicit files (A02 review 082).

Run from the repository root: python -m tools.prepare_ocr_sources --help
A01 and A03-A10 retain the historical 071 behavior; this is not a generic parser.
"""
from pathlib import Path
import json,re,hashlib,shutil,sys
import pypdfium2 as pdf,cv2,numpy as np
from tools.ocr_source_inputs import read_inputs, answer_key_text

def main():
    args,configs=read_inputs()
    P=args.output;P.mkdir(parents=True,exist_ok=False)
    for s in ['sources','pages','crops','contexts']:(P/s).mkdir(exist_ok=True)
    W,H=1334,1888
    def save(n,v):(P/n).write_text(json.dumps(v,ensure_ascii=False,indent=2),encoding='utf-8')
    def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    templates={};keys={};sources=[]
    for cfg in configs:
     sid=cfg['id'];kind=cfg['kind'];last=cfg['last'];split=cfg['split']
     src=args.original;dest=P/'sources'/(sid+'-original.pdf');shutil.copy2(src,dest);cfg['original']=str(src);sources.append({'role':'original','set':sid,'source':str(src),'copy':str(dest),'sha256':sha(src)})
     keydest=P/'sources'/(sid+'-answer-key.pdf');shutil.copy2(args.answer_key,keydest);cfg['answer_key']=str(args.answer_key);cfg['key_first_page']=args.key_first_page;sources.append({'role':'answer-key','set':sid,'source':str(args.answer_key),'copy':str(keydest),'sha256':sha(args.answer_key)})
     keydoc=pdf.PdfDocument(str(keydest));keytext=answer_key_text(keydoc,args.key_first_page)
     d=pdf.PdfDocument(str(dest));expected={};currentpart=0
     for page in range(cfg.get('template_first',2),last+1):
      pattern=1 if page<split else 2
      if page in [2,split]:currentpart=0
      pg=d[page-1];pw,ph=pg.get_size();tp=pg.get_textpage();chars=[tp.get_text_range(i,1) for i in range(tp.count_chars())];txt=''.join(chars)
      def box(i):
       l,b,r,t=tp.get_charbox(i);return [l/pw*W,(ph-t)/ph*H,r/pw*W,(ph-b)/ph*H]
      original=np.array(pg.render(scale=W/pw).to_pil().convert('L').resize((W,H)));cv2.imwrite(str(P/'pages'/f'{sid}-{page:02}-original.png'),original)
      heads=[];parts=list(re.finditer(r'Part\s*(\d+)',txt));floor=180
      if kind=='workbook' and page in cfg.get('warmup_pages',[2,split]):
       warm=re.search(r'Warm[ -]?up',txt,re.I);assert warm,(sid,page,'missing Warm-up');floor=cfg.get('warmup_floors',{}).get(str(page),box(warm.start())[1]-5)
      for m in re.finditer(r'(?<!\d)(\d+)\.\s',txt):
       bb=box(m.start(1));num=int(m.group(1));prev=[x for x in parts if x.start()<m.start()];part=int(prev[-1].group(1)) if prev else currentpart
       if kind!='workbook':part=0
       slot=(pattern,part)
       if num!=expected.get(slot,1) or bb[1]<floor or bb[1]>H-140:continue
       heads.append({'question':num,'index':m.start(1),'box':bb,'pattern':pattern,'part':part});expected[slot]=num+1
      if parts:currentpart=int(parts[-1].group(1))
      for i,h in enumerate(heads):
       end=heads[i+1]['index'] if i+1<len(heads) else len(txt);h['source_text']=txt[h['index']:end];h['char_boxes']=[box(j) for j in range(h['index'],end) if chars[j].strip() and chars[j]!='_'];h['blanks']=[]
       for m in re.finditer(r'_{3,}',txt[h['index']:end]):
        a=box(h['index']+m.start());b=box(h['index']+m.end()-1)
        if abs(a[1]-b[1])<5:h['blanks'].append([a[0],a[1],b[2],b[3]])
       col=h['box'][0]>W/2;after=[a['box'][1] for a in heads if (a['box'][0]>W/2)==col and a['box'][1]>h['box'][1]+5]
       h['zone']=[W//2 if col else 50,int(h['box'][1])-18,W-50 if col else W//2,int(min(after))-18 if after else H-150]
      templates[f'{sid}-{page:02}']={'set':sid,'kind':kind,'page':page,'questions':heads}
      print(sid,page,[(h['part'],h['question']) for h in heads],flush=True)
     (P/(sid+'-key-text.txt')).write_text(keytext,encoding='utf-8');sections=list(re.finditer(r'Pattern\s+([12])(?:\s+Part\s+(\d+))?',keytext))
     for j,msec in enumerate(sections):
      pat=int(msec.group(1));part=int(msec.group(2) or 0);body=keytext[msec.end():sections[j+1].start() if j+1<len(sections) else len(keytext)];matches=list(re.finditer(r'(?<![\d(])(\d+)\)\s*',body));ex=1;valid=[]
      for m in matches:
       if int(m.group(1))==ex:valid.append(m);ex+=1
      for z,m in enumerate(valid):
       raw=body[m.end():valid[z+1].start() if z+1<len(valid) else len(body)].strip();answer=raw.split(':')[0].strip();answer=re.sub(r'\s*-\s*\d+\s*-\s*',' ',answer).replace('Warm-up','').strip()
       if kind=='mc':
        a=re.match(r'([①②③④⑤](?:\s*[,，]\s*[①②③④⑤])*)',raw);answer=a.group(1) if a else ''
       keys[f'{sid}-p{pat}-s{part}-q{m.group(1)}']={'answer':answer,'raw':raw}
     # Canonical question/key coverage is checked before OCR; an omitted template must stop here.
     ids=[f'{sid}-p{h["pattern"]}-s{h["part"]}-q{h["question"]}' for t in templates.values() if t['set']==sid for h in t['questions']];keyids=[k for k in keys if k.startswith(sid+'-')]
     assert set(ids)==set(keyids),(sid,'coverage mismatch',set(keyids)-set(ids),set(ids)-set(keyids))
    save('config.json',configs);save('templates.json',templates);save('keys.json',keys)
    rows=[];questions=[];pages=[];sift=cv2.SIFT_create(nfeatures=6000)
    for cfg in configs:
     for f in sorted(f for f in args.student_dir.iterdir() if f.suffix.lower()=='.jpg'):
      if cfg.get('prefix') and not f.name.startswith(cfg['prefix']):continue
      if not f.stem[-4:].isdigit():continue
      n=int(f.stem[-4:])
      if not cfg['scan_first']<=n<=cfg['scan_last']:continue
      if cfg.get('prefix') and not f.name.startswith(cfg['prefix']):continue
      kind=cfg['kind'];page=n+cfg['page_offset'];sid=f'{cfg["id"]}-{page:02}';temp=templates[sid];copy=P/'sources'/f.name;shutil.copy2(f,copy);sources.append({'role':'student','set':cfg['id'],'source':str(f),'copy':str(copy),'sha256':sha(f)})
      original=cv2.imread(str(P/'pages'/f'{sid}-original.png'),0);native=cv2.imdecode(np.fromfile(str(f),np.uint8),0);small=cv2.resize(native,(W,H));ka,da=sift.detectAndCompute(original,None);kb,db=sift.detectAndCompute(small,None);good=[m for m,n2 in cv2.BFMatcher().knnMatch(da,db,k=2) if m.distance<.7*n2.distance];a=np.float32([ka[m.queryIdx].pt for m in good]);b=np.float32([kb[m.trainIdx].pt for m in good]);M,ok=cv2.findHomography(b,a,cv2.RANSAC,3)
      assert M is not None and ok.sum()>30,(f,'alignment failed')
      aligned=cv2.warpPerspective(small,M,(W,H),borderValue=255);SX=native.shape[1]/W;SY=native.shape[0]/H;high=cv2.warpPerspective(native,np.diag([SX,SY,1])@M@np.diag([1/SX,1/SY,1]),(native.shape[1],native.shape[0]),borderValue=255);cv2.imwrite(str(P/'pages'/f'{sid}-aligned.jpg'),aligned)
      ink=cv2.adaptiveThreshold(aligned,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,14);printed=cv2.dilate((original<195).astype(np.uint8),np.ones((3,3),np.uint8));diff=((ink>0)&(printed==0)).astype(np.uint8)*255;_,lab,stats,_=cv2.connectedComponentsWithStats(diff);clean=np.zeros_like(diff)
      for j,(x,y,w,h,area) in enumerate(stats[1:],1):
       if area>=8 and h>=3:clean[lab==j]=255
      residual=np.linalg.norm(cv2.perspectiveTransform(b[:,None,:],M)[:,0,:]-a,axis=1);pages.append({'source':str(f),'id':sid,'page':page,'kind':kind,'matrix':M.tolist(),'inliers':int(ok.sum()),'median_error':float(np.median(residual[ok.ravel()==1]))})
      overlay=cv2.cvtColor(aligned,cv2.COLOR_GRAY2BGR)
      for h in temp['questions']:
       qid=f'{cfg["id"]}-p{h["pattern"]}-s{h["part"]}-q{h["question"]}';x1,y1,x2,y2=h['zone'];q={**h,'id':qid,'set':cfg['id'],'kind':kind,'page':page,'student':str(f),'segments':[],'key':keys[qid]};boxes=[];context=P/'contexts'/(qid+'.jpg');cv2.imwrite(str(context),high[round(y1*SY):round(y2*SY),round(x1*SX):round(x2*SX)]);q['context']=str(context)
       if kind!='mc' and h['blanks']:
        q['method']='original-underscores'
        for l,t,r,bot in h['blanks']:
         top=t-40;prior=[z[3] for z in h['char_boxes'] if z[2]>l and z[0]<r and top<z[3]<t-6]
         if prior:top=max(prior)+2
         boxes.append([max(x1,int(l)-4),max(y1,int(top)),min(x2,int(r)),min(y2,int(bot)+4)])
       elif kind=='mc':
        q['method']='automatic-difference-components';joined=cv2.morphologyEx(clean[y1:y2,x1:x2],cv2.MORPH_CLOSE,np.ones((5,5),np.uint8));_,_,ss,_=cv2.connectedComponentsWithStats(joined)
        for x,y,w,hh,area in ss[1:]:
         if area>=35 and hh>=8 and w>=3:boxes.append([max(x1,x+x1-4),max(y1,y+y1-4),min(x2,x+x1+w+4),min(y2,y+y1+hh+4)])
       else:
        q['method']='automatic-difference-rows';part=clean[y1:y2,x1:x2];ys=np.where((part>0).sum(axis=1)>=5)[0];groups=[]
        for y in ys:
         if not groups or y>groups[-1][-1]+5:groups.append([int(y)])
         else:groups[-1].append(int(y))
        for g in groups:
         yy,xx=np.where(part[g[0]:g[-1]+1]>0)
         if g[-1]-g[0]>=7 and len(xx)>=60:boxes.append([max(x1,x1+int(xx.min())-4),max(y1,y1+g[0]-4),min(x2,x1+int(xx.max())+5),min(y2,y1+g[-1]+5)])
       for i,(l,t,r,bot) in enumerate(boxes,1):
        if r<=l or bot<=t:continue
        ident=f'{qid}-r{i:02}';dest=P/'crops'/(ident+'.png');crop=high[round(t*SY):round(bot*SY),round(l*SX):round(r*SX)];cv2.imwrite(str(dest),cv2.copyMakeBorder(crop,10,10,10,10,cv2.BORDER_CONSTANT,value=255));rows.append({'id':ident,'question_id':qid,'input':str(dest),'box':list(map(int,[l,t,r,bot]))});q['segments'].append(ident);cv2.rectangle(overlay,(int(l),int(t)),(int(r),int(bot)),(0,0,230),1)
       questions.append(q)
      cv2.imwrite(str(P/'pages'/f'{sid}-regions.jpg'),overlay);print(sid,'crops',len(rows),flush=True);save('sources.json',sources);save('pages.json',pages);save('questions.json',questions);save('regions.json',rows)
    print('TOTAL',len(questions),len(rows),flush=True)

if __name__ == "__main__":
    main()
