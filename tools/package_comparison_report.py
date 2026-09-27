"""Embed existing report pages and original image bytes for offline transfer."""
import argparse
import base64
import html
import json
from pathlib import Path
import re


def package(root, output):
    if output.exists():
        raise ValueError('Use a new output file')
    reports, images, paths = {}, {}, {}
    for key, name in [('compare','report.html'),('broad','broad.html'),('duplicate','duplicate.html')]:
        text=(root/name).read_text(encoding='utf-8')
        def embed(match):
            path=(root/html.unescape(match.group(1))).resolve()
            mime={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png'}.get(path.suffix.lower())
            if mime is None:
                raise ValueError(f'Not an image: {path}')
            if path not in paths:
                ident=f'image{len(paths)}';paths[path]=ident
                images[ident]='data:'+mime+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
            return 'data-asset="'+paths[path]+'"'
        text=re.sub(r'src="([^"]+)"',embed,text)
        for target,dest in [('report.html','compare'),('broad.html','broad'),('duplicate.html','duplicate')]:
            text=text.replace('href="'+target+'"','href="#" onclick="parent.showReport(\''+dest+'\'); return false;"')
        reports[key]=text
    data=json.dumps(dict(reports=reports,images=images),ensure_ascii=False).replace('<','\\u003c')
    page='''<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>OCR 두 조건 비교 · 사진 포함</title><style>body{margin:0;font:16px system-ui;background:#f4f6fa}nav{padding:12px;display:flex;gap:8px;flex-wrap:wrap}button{font:inherit;padding:8px 12px;cursor:pointer}iframe{width:100%;height:calc(100vh - 75px);border:0}</style><nav><button onclick="showReport('duplicate')">기본 · 제안안</button><button onclick="showReport('compare')">두 조건 비교</button><button onclick="showReport('broad')">참고 · 사용자안 · 독립 검증에서 틀린 자동확정 1건</button></nav><iframe id="report" title="OCR 비교 결과"></iframe><script>const data='''+data+''';const frame=document.getElementById('report');frame.onload=()=>frame.contentDocument.querySelectorAll('img[data-asset]').forEach(img=>img.src=data.images[img.dataset.asset]);function showReport(name){frame.srcdoc=data.reports[name];}showReport('duplicate');</script></html>'''
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(page,encoding='utf-8')
    print(json.dumps(dict(file=str(output.resolve()),bytes=output.stat().st_size,unique_images=len(images),reports=len(reports))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();package(a.root,a.output)
