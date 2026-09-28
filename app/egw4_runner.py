"""New-file orchestration of the unchanged f5fed75 local grading engine."""
import argparse
import atexit
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import shutil
import subprocess
import sys
import time
import traceback

REPO = Path(__file__).resolve().parents[1]
COMMIT = 'f5fed7568b669b5206cf47c6b16eb6bd9f26c775'
FROZEN_ENGINE_SHA256 = '08a7c408fb2f0ee54ad7ce096c304f45b667240decaceb4ad491a20f12680f54'
sys.path.insert(0, str(REPO))
sys.dont_write_bytecode = True


def emit(**value):
    print('EGW4_EVENT '+json.dumps(value, ensure_ascii=False), flush=True)


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def engine_hashes():
    return {str(p.resolve()):sha(p) for folder in ('tools', 'src', 'tests')
            for p in (REPO/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts}


def verify_engine_version():
    """Refuse a changed engine before importing OCR; no Git installation needed."""
    digest = hashlib.sha256()
    files = sorted((p.relative_to(REPO).as_posix(), p)
                   for folder in ('tools', 'src', 'rules') for p in (REPO/folder).rglob('*')
                   if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ('.pyc', '.pyo'))
    for relative, path in files:
        content = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).digest()
        digest.update(relative.encode('utf-8') + b'\0' + content)
    if digest.hexdigest() != FROZEN_ENGINE_SHA256:
        raise ValueError('채점기 파일이 검증 기준 f5fed75와 다릅니다. 이 버전의 실행 폴더를 사용해 주세요.')


def install_network_audit(path):
    """Block the same Python connect/DNS events as the existing OCR runner."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    state = dict(pid=os.getpid(), started_at=datetime.now(timezone.utc).isoformat(), attempts=[],
                 scope='Python socket.connect / socket.getaddrinfo; not OS-wide or native-library proof')
    save(path, state)

    def write():
        save(path, state)

    def audit(event, args):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            state['attempts'].append(dict(event=event, arguments=repr(args[1:] if event=='socket.connect' else args),
                time=datetime.now(timezone.utc).isoformat(), blocked=True))
            write()
            raise RuntimeError('외부 연결 시도를 차단했습니다: '+event)

    sys.addaudithook(audit)
    atexit.register(write)
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
    return state


def run_child(command, log_path, progress=None):
    environment = dict(os.environ, PYTHONPATH=str(REPO), PYTHONIOENCODING='utf-8',
                       PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with Path(log_path).open('x', encoding='utf-8') as log:
        child = subprocess.Popen(command, cwd=REPO, env=environment, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                 errors='replace', creationflags=flags)
        for line in child.stdout:
            log.write(line); log.flush()
            if line.startswith('EGW4_EVENT '):
                print(line.rstrip(), flush=True)
            elif progress:
                try:
                    value = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(value, dict):
                    progress(value)
        code = child.wait()
    if code:
        raise RuntimeError(f'처리 단계가 중단됐습니다. 기록: {Path(log_path).resolve()}')


def select_scans(profile, folder):
    folder = Path(folder).resolve()
    if not folder.is_dir():
        raise ValueError('학생 스캔 폴더가 없습니다.')
    mappings = profile['scan_mappings']
    known = [m for m in mappings if any(Path(p).resolve()==folder for p in m.get('known_folders', []))]
    if len(known)>1:
        raise ValueError('이 폴더에 등록된 스캔 범위가 중복됩니다. 교재 등록을 확인해 주세요.')

    def files(mapping):
        rows = {}
        for path in sorted(folder.iterdir()):
            match = re.search(r'(\d{4})$', path.stem)
            if (not path.is_file() or path.suffix.lower()!='.jpg' or not match
                    or not path.name.startswith(mapping.get('prefix', ''))):
                continue
            number = int(match.group(1))
            if mapping['scan_first']<=number<=mapping['scan_last']:
                if number in rows:
                    raise ValueError('같은 스캔 번호의 JPG가 둘 이상 있습니다. 입력 폴더를 확인해 주세요.')
                rows[number] = path
        expected = set(range(mapping['scan_first'], mapping['scan_last']+1))
        return rows if set(rows)==expected else None

    matches = [(m, files(m)) for m in (known or mappings)]
    matches = [(m, rows) for m, rows in matches if rows is not None]
    if len(matches)!=1:
        raise ValueError('등록된 스캔 범위와 정확히 맞는 입력을 하나로 정할 수 없습니다. 교재와 폴더를 확인해 주세요.')
    mapping, rows = matches[0]
    return mapping, rows


def prepare_source(profile, scans, mapping, output):
    """Registered textbook + fresh scans; same 6000/.7/3 alignment as EGW3 f5."""
    import cv2
    import numpy as np
    old = Path(profile['source']).resolve()
    output.mkdir(parents=True)
    for folder in ('sources', 'pages', 'contexts'):
        (output/folder).mkdir()
    for filename in ('templates.json', 'keys.json', 'config.json'):
        if (old/filename).is_file():
            shutil.copyfile(old/filename, output/filename)
    original_questions = read(old/'questions.json')
    set_id = profile['set_id']
    if {q['set'] for q in original_questions}!={set_id}:
        raise ValueError('등록된 교재 세트와 문항 목록이 다릅니다.')
    shutil.copyfile(old/'sources'/f'{set_id}-original.pdf', output/'sources'/f'{set_id}-original.pdf')
    references = {p['page']:p for p in read(old/'pages.json')}
    expected_pages = {n+mapping['page_offset'] for n in scans}
    if expected_pages != set(references):
        raise ValueError('스캔 번호와 교재 페이지 연결이 등록된 범위와 다릅니다.')
    tracked = {str(p.resolve()):sha(p) for p in [old/'questions.json', old/'pages.json',
        old/'keys.json', old/'templates.json', old/'sources'/f'{set_id}-original.pdf', *scans.values()]}
    pages = []; questions = []; sift = cv2.SIFT_create(nfeatures=6000)
    emit(stage='alignment', done=0, total=len(scans), message='스캔과 교재 페이지를 맞추고 있습니다.')
    for index, (number, original_scan) in enumerate(sorted(scans.items()), 1):
        before = references[number+mapping['page_offset']]
        ident = before['id']; scan = output/'sources'/original_scan.name
        shutil.copyfile(original_scan, scan)
        ref = output/'pages'/f'{ident}-original.png'
        tracked[str((old/'pages'/ref.name).resolve())] = sha(old/'pages'/ref.name)
        shutil.copyfile(old/'pages'/ref.name, ref)
        original = cv2.imread(str(ref), 0); native = cv2.imdecode(np.fromfile(scan, np.uint8), 0)
        if original is None or native is None:
            raise ValueError('교재 또는 학생 JPG를 읽을 수 없습니다.')
        small = cv2.resize(native, (1334, 1888))
        ka, da = sift.detectAndCompute(original, None); kb, db = sift.detectAndCompute(small, None)
        good = [m for m,n2 in cv2.BFMatcher().knnMatch(da, db, k=2) if m.distance < .7*n2.distance]
        a = np.float32([ka[m.queryIdx].pt for m in good]); b = np.float32([kb[m.trainIdx].pt for m in good])
        matrix, ok = cv2.findHomography(b, a, cv2.RANSAC, 3)
        if matrix is None or ok.sum()<=30:
            raise ValueError(f'교재 {before["page"]}쪽과 스캔을 맞추지 못했습니다. 페이지를 확인해 주세요.')
        residual = np.linalg.norm(cv2.perspectiveTransform(b[:,None,:], matrix)[:,0,:]-a, axis=1)
        median = float(np.median(residual[ok.ravel()==1]))
        if median>3:
            raise ValueError(f'교재 {before["page"]}쪽의 정렬 확인이 필요합니다.')
        aligned = cv2.warpPerspective(small, matrix, (1334,1888), borderValue=255)
        assert cv2.imwrite(str(output/'pages'/f'{ident}-aligned.jpg'), aligned)
        sx, sy = native.shape[1]/1334, native.shape[0]/1888
        high = cv2.warpPerspective(native, np.diag([sx,sy,1])@matrix@np.diag([1/sx,1/sy,1]),
                                  (native.shape[1],native.shape[0]), borderValue=255)
        page = dict(source=str(scan), id=ident, page=before['page'], kind=before['kind'],
                    scan_short_side=int(min(native.shape)), matrix=matrix.tolist(),
                    inliers=int(ok.sum()), median_error=median)
        pages.append(page)
        for original_question in original_questions:
            if original_question['page']!=page['page']:
                continue
            question = dict(original_question, student=str(scan), segments=[])
            l,t,r,bot = question['zone']; path = output/'contexts'/f'{question["id"]}.jpg'
            assert cv2.imwrite(str(path), high[round(t*sy):round(bot*sy), round(l*sx):round(r*sx)])
            question['context'] = str(path); questions.append(question)
        emit(stage='alignment', done=index, total=len(scans), message='스캔과 교재 페이지를 맞추고 있습니다.')
    if len(questions)!=len(read(output/'keys.json')):
        raise ValueError('등록된 문항과 답지의 개수가 다릅니다.')
    save(output/'pages.json', pages); save(output/'questions.json', questions); save(output/'regions.json', [])
    save(output/'EGW4-source.json', dict(mapping=mapping, input_sha256=tracked, source=str(old)))
    return tracked


def run(book, student_dir, output):
    verify_engine_version()
    output = Path(output).resolve(); book = Path(book).resolve(); student_dir = Path(student_dir).resolve()
    if output.exists():
        raise ValueError('출력 폴더가 이미 있습니다. 기존 결과를 덮어쓰지 않도록 새 폴더를 지정해 주세요.')
    profile = read(book)
    if profile.get('schema_version')!=1:
        raise ValueError('지원하지 않는 교재 등록 형식입니다.')
    mapping, scans = select_scans(profile, student_dir)
    model = Path(profile['model_dir']).resolve(); templates = Path(profile['templates_dir']).resolve()
    if not model.is_dir() or not (model/'inference.json').is_file():
        raise ValueError('등록된 로컬 OCR 모델을 찾을 수 없습니다.')
    if not all((templates/f'{i}.png').is_file() for i in range(1,6)):
        raise ValueError('등록된 번호 템플릿을 찾을 수 없습니다.')
    for protected in (student_dir, Path(profile['source']).resolve(), model, templates):
        if output.is_relative_to(protected):
            raise ValueError('원자료 폴더 안에는 결과를 저장할 수 없습니다. 별도 출력 폴더를 지정해 주세요.')
    output.mkdir(parents=True)
    audit_dir = output/'network-audit'
    install_network_audit(audit_dir/'runner.json')
    started = time.perf_counter()
    engine = engine_hashes()
    tracked = {str(p):sha(p) for p in [book, *model.glob('inference.*'), *[templates/f'{i}.png' for i in range(1,6)]]}
    emit(stage='prepare', done=0, total=len(scans), message='등록된 교재와 스캔 범위를 확인했습니다. 새 판독을 시작합니다.')
    tracked.update(prepare_source(profile, scans, mapping, output/'source'))
    run_child([sys.executable, str(REPO/'app/egw4_fresh_ocr.py'), '--source', str(output/'source'),
               '--output', str(output/'grading'), '--model', str(model), '--audit-dir', str(audit_dir)],
              output/'EGW4-ocr.log')
    from tools.choice_mark_recommendations import inspect, attach
    from tools.dual_evidence import run as dual_evidence
    from tools.package_result_review import package
    from src.result_files import load_result
    grading = output/'grading'; view = output/'source-view'
    shutil.copytree(output/'source', view)
    save(view/'questions.json', read(grading/'assigned/questions.json'))
    trial = output/'trial'
    for folder in ('baseline', 'assigned', 'comparison'):
        (trial/folder).mkdir(parents=True)
    shutil.copyfile(grading/'review/classification.json', trial/'baseline/classification.json')
    shutil.copyfile(grading/'assigned/results.json', trial/'assigned/results.json')
    for mode in ('duplicate', 'broad'):
        shutil.copyfile(grading/'review/comparison'/f'{mode}.json', trial/'comparison'/f'{mode}.json')
    emit(stage='marks', done=0, total=len(scans), message='인쇄 번호의 선택 표시를 확인하고 있습니다.')
    inspect(grading/'review/result/duplicate/result.json', templates, output/'measurements')
    emit(stage='marks', done=len(scans), total=len(scans), message='선택 표시 확인이 끝났습니다.')
    emit(stage='agreement', done=0, total=len(scans), message='손글씨와 선택 표시를 비교하고 보류 사유를 확인하고 있습니다.')
    dual_evidence(grading/'review/result', trial, view, output/'measurements/measurements.json', output/'dual')
    summaries = {}
    for mode in ('duplicate', 'broad'):
        recommendations = attach(output/'dual'/mode/'result.json', output/'measurements/measurements.json', output/'result'/mode)
        result = load_result(output/'result'/mode/'result.json')
        automatic = sum(q['judgement']!='보류' for q in result['questions'])
        summaries[mode] = dict(questions=len(result['questions']), automatic=automatic,
                               held=len(result['questions'])-automatic, recommendations=len(recommendations))
    emit(stage='agreement', done=len(scans), total=len(scans), message='최종 채점 결과를 저장했습니다.')
    emit(stage='report', done=0, total=len(scans), message='교사 확인용 보고서를 만들고 있습니다.')
    report = output/'EGW4-result.html'
    package(output/'result', report)
    for path, digest in {**tracked, **engine}.items():
        if sha(path)!=digest:
            raise ValueError('실행 중 입력 또는 채점 파일이 바뀌었습니다. 결과 기록을 확인해 주세요.')
    network = [read(p) for p in audit_dir.glob('*.json')]
    attempts = sum(len(p['attempts']) for p in network)
    if attempts:
        raise RuntimeError('외부 연결 시도가 차단되어 완료 결과로 표시하지 않습니다. 통신 기록을 확인해 주세요.')
    elapsed = time.perf_counter()-started
    final_result = load_result(output/'result/duplicate/result.json')
    reasons = Counter(r['message'] for q in final_result['questions'] for r in q['reasons'])
    completion = dict(event='complete', report=str(report), output=str(output), summary=summaries['duplicate'],
        policies=summaries, total_seconds=elapsed, seconds_per_page=elapsed/len(scans), pages=len(scans),
        network_attempts=attempts, network_scope='Python socket/DNS 감사; OS·네이티브 전체 무통신 검증 아님',
        held_messages=[message for message,count in reasons.most_common(5)] if summaries['duplicate']['automatic']==0 else [])
    save(output/'EGW4-execution.json', dict(commit=COMMIT, fresh_ocr=True, previous_run_ocr_reused=0,
        book_id=profile['id'], mapping_id=mapping['id'], input_sha256=tracked, engine_sha256=engine,
        **completion))
    emit(stage='report', done=len(scans), total=len(scans), message='교사 확인용 보고서가 준비됐습니다.')
    emit(**completion)
    return completion


def main():
    if len(sys.argv)>1 and sys.argv[1]=='--worker-module':
        module, audit_path, *arguments = sys.argv[2:]
        install_network_audit(audit_path)
        sys.argv = [module, *arguments]
        runpy.run_module(module, run_name='__main__')
        return
    parser = argparse.ArgumentParser(description='등록된 교재로 새 스캔을 로컬 채점합니다.')
    for name in ('book', 'student-dir', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    try:
        run(args.book, args.student_dir, args.output)
    except Exception as error:
        emit(event='error', message='채점이 중단됐습니다. 입력과 실행 기록을 확인해 주세요.',
             detail=str(error), output=str(args.output.resolve()))
        traceback.print_exc()
        raise SystemExit(1)


if __name__=='__main__':
    main()
