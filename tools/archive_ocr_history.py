"""Archive local OCR evidence; never infer new scores or rewrite source outputs."""
from pathlib import Path
import sqlite3,json,hashlib,csv,io,datetime,html,argparse,os
ap=argparse.ArgumentParser();ap.add_argument('--date',default='20260924');args=ap.parse_args()
root=Path(__file__).resolve().parents[1];private=root/'private';out=private/'ocr-history-db';out.mkdir(exist_ok=True)
now=datetime.datetime.now(datetime.timezone.utc).isoformat();dbpath=out/f'ocr-{args.date}.sqlite3'
if dbpath.exists():
 raise SystemExit('Existing snapshot preserved; choose another date/output before rebuilding.')
c=sqlite3.connect(dbpath);c.execute('PRAGMA foreign_keys=ON')
c.executescript('''
CREATE TABLE imports(id INTEGER PRIMARY KEY, imported_at_utc TEXT, date_scope TEXT, note TEXT);
CREATE TABLE artifacts(id INTEGER PRIMARY KEY, experiment TEXT, path TEXT UNIQUE, sha256 TEXT, bytes INTEGER, suffix TEXT, content BLOB, parse_error TEXT);
CREATE TABLE score_records(id INTEGER PRIMARY KEY, artifact_id INTEGER REFERENCES artifacts(id), json_pointer TEXT, field TEXT, text TEXT, score REAL, score_scale TEXT, context_json TEXT, representation TEXT);
CREATE TABLE assessment_records(id INTEGER PRIMARY KEY, artifact_id INTEGER REFERENCES artifacts(id), json_pointer TEXT, payload_json TEXT);
CREATE INDEX scores_by_artifact ON score_records(artifact_id);
CREATE VIEW scores AS SELECT s.*,a.experiment,a.path AS source_path FROM score_records s JOIN artifacts a ON a.id=s.artifact_id;
''')
c.execute('INSERT INTO imports VALUES(1,?,?,?)',(now,args.date,'Evidence snapshot, not unique inference counts. Scores are model outputs, not calibrated probabilities. Source dates are folder labels, not inferred execution timestamps.'))
files=[]
for d in sorted(private.iterdir()):
 if d.is_dir() and args.date in d.name:
  files.extend(f for f in sorted(d.rglob('*')) if f.is_file() and not any(v in f.relative_to(d).parts for v in ['models','__pycache__','.git']))
 elif d.is_file() and args.date in d.name:files.append(d)
text_ext={'.json','.tsv','.csv','.txt','.log','.md','.py','.html'}
errors=[];unhandled=[]
def enc(v):return json.dumps(v,ensure_ascii=False)
def ptr(k):return str(k).replace('~','~0').replace('/','~1')
def walk(x,aid,path='',ctx=None,representation='source-or-summary'):
 if isinstance(x,list):
  for i,v in enumerate(x):walk(v,aid,path+'/'+str(i),ctx,representation)
  return
 if not isinstance(x,dict):return
 context=dict(ctx or {})
 for k in ['id','name','question','q','slot','kind','group','input','input_path','reference','reference_status','teacher','key','box']:
  if k in x:context[k]=x[k]
 # Keep grade/hold/teacher data verbatim: no automatic grading during import.
 if any(k in x for k in ['teacher','teacher_selection','teacher_grade','diagnostic_grade','forced_exact_grade','tentative_selection','status','counts','correct_to_correct','matches','match','before_match','reference_status']):
  c.execute('INSERT INTO assessment_records(artifact_id,json_pointer,payload_json) VALUES(?,?,?)',(aid,path,enc(x)))
 for k,v in x.items():
  if 'score' not in k.lower():continue
  if isinstance(v,(int,float)) and not isinstance(v,bool):
   text=x.get({'rec_score':'rec_text','ocr_score':'ocr_text','before_score':'before','after_score':'after'}.get(k,'text'))
   c.execute('INSERT INTO score_records(artifact_id,json_pointer,field,text,score,score_scale,context_json,representation) VALUES(?,?,?,?,?,?,?,?)',(aid,path+'/'+ptr(k),k,None if text is None else (text if isinstance(text,str) else enc(text)),v,'model-native; not calibrated probability',enc(context),representation))
  elif isinstance(v,list) and all(isinstance(z,(int,float)) for z in v):
   texts=x.get('rec_texts',x.get('texts',[]))
   for i,score in enumerate(v):
    c.execute('INSERT INTO score_records(artifact_id,json_pointer,field,text,score,score_scale,context_json,representation) VALUES(?,?,?,?,?,?,?,?)',(aid,path+'/'+ptr(k)+'/'+str(i),k,texts[i] if i<len(texts) else None,score,'model-native; not calibrated probability',enc(context),representation))
  elif not isinstance(v,(dict,list,bool)) and v is not None:unhandled.append([aid,path,k])
 for k,v in x.items():
  if isinstance(v,(dict,list)):walk(v,aid,path+'/'+ptr(k),context,representation)
for f in files:
 raw=f.read_bytes();rel=f.relative_to(root).as_posix();experiment=f.relative_to(private).parts[0]
 aid=c.execute('INSERT INTO artifacts(experiment,path,sha256,bytes,suffix,content) VALUES(?,?,?,?,?,?)',(experiment,rel,hashlib.sha256(raw).hexdigest(),len(raw),f.suffix,raw if f.suffix.lower() in text_ext else None)).lastrowid
 try:
  if f.suffix=='.json':
   x=json.loads(raw.decode('utf-8-sig'));walk(x,aid,representation='derived-or-aggregate' if f.name in ['comparison.json','evaluation.json','predictions.json','repeat-summary.json','results.json','extra-results.json','audit.json'] else 'source-or-metadata')
  elif f.suffix=='.tsv':
   for n,row in enumerate(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')),delimiter='\t'),2):
    if 'conf' in row:
     score=float(row['conf']);c.execute('INSERT INTO score_records(artifact_id,json_pointer,field,text,score,score_scale,context_json,representation) VALUES(?,?,?,?,?,?,?,?)',(aid,'line:'+str(n),'conf',row.get('text'),score,'Tesseract 0..100; -1 = non-word/no confidence',enc(row),'tsv-source'))
 except (ValueError,UnicodeError) as e:
  errors.append([rel,str(e)]);c.execute('UPDATE artifacts SET parse_error=? WHERE id=?',(str(e),aid))
c.commit()
assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
assert not c.execute('PRAGMA foreign_key_check').fetchall()
assert c.execute('SELECT count(*) FROM artifacts').fetchone()[0]==len(files)
# Verify archived bytes exactly match source hashes.
for sha,blob in c.execute('SELECT sha256,content FROM artifacts WHERE content IS NOT NULL'):assert hashlib.sha256(blob).hexdigest()==sha
summary={'imported_at_utc':now,'artifacts':len(files),'archived_text_files':c.execute('SELECT count(*) FROM artifacts WHERE content IS NOT NULL').fetchone()[0],'experiment_groups':c.execute('SELECT count(DISTINCT experiment) FROM artifacts').fetchone()[0],'score_occurrences':c.execute('SELECT count(*) FROM score_records').fetchone()[0],'assessment_nodes':c.execute('SELECT count(*) FROM assessment_records').fetchone()[0],'parse_errors':errors,'unhandled_score_fields':unhandled,'integrity_check':'ok','note':'Occurrences include duplicated reports, arrays, and Tesseract non-word rows; NOT unique trials/questions. Original/student print OCR and student answers are both present.'}
(out/'summary.json').write_text(enc(summary),encoding='utf-8')
data=[dict(zip(['experiment','source','pointer','field','text','score','scale','representation','context'],r)) for r in c.execute('SELECT experiment,source_path,json_pointer,field,text,score,score_scale,representation,context_json FROM scores ORDER BY experiment,source_path,json_pointer')]
# Safe embedded JSON; render source strings only via textContent.
payload=enc(data).replace('<','\\u003c');summ=html.escape(enc(summary))
page=r'''<!doctype html><html lang="ko"><meta charset="utf-8"><title>OCR 시험 기록 DB</title><style>body{font-family:Segoe UI,Malgun Gothic,sans-serif;margin:24px;color:#17283c}input,select{padding:10px;margin:6px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:8px;border:1px solid #ddd;word-break:break-word}th{background:#eef3f8}pre{white-space:pre-wrap}details{margin:16px 0}</style><h1>OCR 시험 기록 DB · 2026-09-24</h1><p>OCR 출력 점수와 평가 기록을 원문 그대로 보존한 로컬 스냅샷입니다. 중복 인용·원본 인쇄체·학생 필기·문자가 아닌 행이 포함되어 건수는 독립 시험 수가 아닙니다. 학생 성적 점수는 새로 계산하지 않았습니다.</p><p>0.8은 이전 자동 위치 시험에서 assistant가 설정한 미검증 후처리 기준입니다. DB 가져오기에서는 이 기준을 새로 적용하거나 원문 점수를 바꾸지 않았습니다. 모델 점수와 보류/채점 판정을 구별합니다.</p><label>시험 <select id="experiment"><option value="">전체</option></select></label><label>검색 <input id="query" placeholder="문자·문항·파일명"></label><label>최소 원점수 <input id="minimum" type="number" step="any"></label><p id="count"></p><button id="prev">이전</button><button id="next">다음</button><table><thead><tr><th>시험 / 원본 위치</th><th>OCR 원문</th><th>모델 원점수 / 척도</th><th>근거·문항·입력 정보</th></tr></thead><tbody id="rows"></tbody></table><details><summary>수집·검증 요약</summary><pre>SUMMARY</pre></details><script id="data" type="application/json">PAYLOAD</script><script>const data=JSON.parse(document.getElementById('data').textContent),exp=document.getElementById('experiment'),q=document.getElementById('query'),min=document.getElementById('minimum');let page=0;for(const x of [...new Set(data.map(x=>x.experiment))]){const o=document.createElement('option');o.value=x;o.textContent=x;exp.append(o)}function render(){const a=data.filter(x=>(!exp.value||x.experiment===exp.value)&&JSON.stringify(x).toLowerCase().includes(q.value.toLowerCase())&&(min.value===''||x.score>=Number(min.value)));page=Math.max(0,Math.min(page,Math.max(0,Math.ceil(a.length/100)-1)));document.getElementById('count').textContent=a.length+'개 점수 기록 · '+(page+1)+'쪽 (100개씩)';const body=document.getElementById('rows');body.replaceChildren();for(const x of a.slice(page*100,(page+1)*100)){const tr=document.createElement('tr');for(const s of [x.experiment+'\n'+x.source+' #'+x.pointer,x.text??'(연결된 문자 미기록)',String(x.score)+'\n'+x.scale,x.context+'\n'+x.representation]){const td=document.createElement('td');td.textContent=s;tr.append(td)}body.append(tr)}}for(const el of [exp,q,min])el.addEventListener('input',()=>{page=0;render()});document.getElementById('prev').onclick=()=>{page--;render()};document.getElementById('next').onclick=()=>{page++;render()};render();</script></html>'''
(out/'index.html').write_text(page.replace('SUMMARY',summ).replace('PAYLOAD',payload),encoding='utf-8')
parts=[]
for source,pointer,payload in c.execute('SELECT a.path,r.json_pointer,r.payload_json FROM assessment_records r JOIN artifacts a ON a.id=r.artifact_id'):
 parts.append('<details><summary>'+html.escape(source+' #'+pointer)+'</summary><pre>'+html.escape(json.dumps(json.loads(payload),ensure_ascii=False,indent=2))+'</pre></details>')
(out/'assessments.html').write_text('<!doctype html><html lang="ko"><meta charset="utf-8"><title>평가 원문</title><a href="index.html">OCR 점수 검색</a><h1>교사 전사·채점·보류 기록</h1><p>중복 인용 및 과거 평가 포함. 원문에 없는 정보는 만들지 않았습니다.</p>'+''.join(parts)+'</html>',encoding='utf-8')
f=out/'index.html';f.write_text(f.read_text(encoding='utf-8').replace('<h1>','<a href="assessments.html">평가 원문 보기</a><h1>',1),encoding='utf-8')
c.close();print(enc(summary))
