"""Local contract-verification screen, not a packaged grading application."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
from urllib.parse import parse_qs, urlparse

from src.result_files import ResultFileError, image_path, load_result, load_state, save_correction
from src.result_files import review_result_path, review_policy_label


def make_server(result_path, port=8140):
    result_path = review_result_path(result_path).resolve()
    load_state(result_path)  # Refuse invalid results/corrections before opening a listener.
    token = secrets.token_urlsafe(24)
    template = Path(__file__).parents[1]/'src/result-review.html'

    class Handler(BaseHTTPRequestHandler):
        def send_bytes(self, code, raw, content_type):
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy',
                f"default-src 'none'; script-src 'nonce-{token}'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers(); self.wfile.write(raw)

        def send_json(self, code, value):
            self.send_bytes(code, json.dumps(value, ensure_ascii=False).encode('utf-8'), 'application/json; charset=utf-8')

        def valid_host(self):
            return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

        def do_GET(self):
            if not self.valid_host():
                self.send_json(403, dict(error='허용되지 않은 접근입니다.')); return
            parsed = urlparse(self.path)
            try:
                if parsed.path == '/':
                    page = template.read_text(encoding='utf-8').replace('__TOKEN__', token).replace('__POLICY_LABEL__', review_policy_label(result_path))
                    self.send_bytes(200, page.encode('utf-8'), 'text/html; charset=utf-8')
                elif parsed.path == '/api/state':
                    self.send_json(200, load_state(result_path))
                elif parsed.path == '/image':
                    args = parse_qs(parsed.query)
                    result = load_result(result_path)
                    q = next(q for q in result['questions'] if q['id'] == args['question'][0])
                    item = next(e for e in q['evidence_images'] if e['id'] == args['evidence'][0])
                    path = image_path(result_path.parent, item['path'])
                    self.send_bytes(200, path.read_bytes(), 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg')
                else:
                    self.send_json(404, dict(error='없는 항목입니다.'))
            except (ResultFileError, OSError, KeyError, StopIteration) as error:
                self.send_json(400, dict(error=str(error) if isinstance(error, ResultFileError) else '근거 파일을 읽을 수 없습니다.'))

        def do_POST(self):
            expected_origin = f'http://127.0.0.1:{self.server.server_port}'
            if (not self.valid_host() or self.headers.get('Origin') != expected_origin
                    or not secrets.compare_digest(self.headers.get('X-Review-Token', ''), token)):
                self.send_json(403, dict(error='허용되지 않은 저장 요청입니다.')); return
            if self.path != '/api/correction':
                self.send_json(404, dict(error='없는 저장 경로입니다.')); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ResultFileError('저장 내용의 크기를 확인하세요.')
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ResultFileError('저장 요청 형식이 잘못됐습니다.')
                state = save_correction(result_path, data['question_id'], data['read_answer'], data['judgement'],
                                        data['note'], data['revision'], data['result_id'])
                self.send_json(200, state)
            except (ResultFileError, ValueError, KeyError, OSError) as error:
                self.send_json(409, dict(error=str(error) if isinstance(error, ResultFileError) else '저장하지 못했습니다. 기존 파일은 보존됩니다.'))

        def log_message(self, fmt, *args):
            pass

    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('result',type=Path);p.add_argument('--port',type=int,default=8140)
    a=p.parse_args()
    with make_server(a.result,a.port) as server:
        print(f'http://127.0.0.1:{server.server_port}', flush=True)
        server.serve_forever()
