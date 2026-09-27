"""Single-file offline copy of the same result UI, with correction JSON transfer."""
import argparse
import base64
import json
from pathlib import Path

from src.result_files import image_path, load_state
from src.result_files import review_result_path, review_policy_label


def package(result_path, output):
    result_path = review_result_path(result_path)
    state = load_state(result_path)
    images = {}
    for q in state['result']['questions']:
        for e in q['evidence_images']:
            if e['path'] not in images:
                path = image_path(result_path.parent, e['path'])
                mime = 'image/png' if path.suffix.lower() == '.png' else 'image/jpeg'
                images[e['path']] = f'data:{mime};base64,' + base64.b64encode(path.read_bytes()).decode('ascii')
    data = json.dumps(dict(result=state['result'], corrections=state['corrections'], images=images), ensure_ascii=False).replace('<', '\\u003c')
    template = (Path(__file__).parents[1]/'src/result-review.html').read_text(encoding='utf-8')
    script = (Path(__file__).parents[1]/'src/result-portable.js').read_text(encoding='utf-8')
    marker = '<script nonce="__TOKEN__">'
    assert template.count(marker) == 1
    page = template.replace(marker, '<script nonce="__TOKEN__">\nconst portableData=' + data + ';\n' + script + '\n</script>\n' + marker)
    page = page.replace('<button id="reload">', '<div><button id="import-corrections">교사 수정 JSON 불러오기</button><input id="correction-file" type="file" accept=".json,application/json" hidden><button id="reload">')
    page = page.replace('결과 다시 불러오기</button></header>', '화면 다시 불러오기</button></div></header>')
    page = page.replace('파일 계약 검증용 화면 · 자동 판정과 교사 확인을 따로 보존합니다.', '다른 PC용 · 사진 포함 · 수정은 JSON 다운로드로 보관합니다.')
    page = page.replace('교사 수정 저장</button>', '교사 수정 JSON 다운로드</button>')
    page = page.replace('자동 결과 파일은 바꾸지 않습니다.', 'HTML에는 수정이 저장되지 않습니다. 다운로드한 JSON을 보관하고, 다시 열 때 위에서 불러오세요.')
    page = page.replace('<meta charset="utf-8">', '<meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'nonce-offline-review\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'none\'; base-uri \'none\'">')
    page = page.replace('__TOKEN__', 'offline-review').replace('__POLICY_LABEL__', review_policy_label(result_path))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8') as stream:
        stream.write(page)
    return dict(file=str(output.resolve()), bytes=output.stat().st_size, questions=len(state['result']['questions']), images=len(images))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('result', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    print(json.dumps(package(args.result, args.output), ensure_ascii=False))
