"""Read original scan dimensions; never resize pixels or change OCR candidates."""
from pathlib import Path

from PIL import Image


def inspect_scan_sizes(pages, source):
    """Use the same frozen student copy as extraction, including older batches."""
    inspected = []
    for page in pages:
        page = dict(page)
        if page.get('source'):
            scan = source/'sources'/Path(page['source']).name
            if not scan.is_file():
                scan = Path(page['source'])
            # Missing/unreadable scans raise instead of silently allowing confirmation.
            with Image.open(scan) as image:
                page['scan_short_side'] = min(image.size)
        inspected.append(page)
    return inspected


def resolution_reason(page):
    short_side = (page or {}).get('scan_short_side')
    if short_side is not None and not 2400 <= short_side <= 2560:
        return f'스캔 해상도 확인 필요: 300dpi로 스캔해 주세요 (현재 짧은 변 {short_side} px)'
    return None
