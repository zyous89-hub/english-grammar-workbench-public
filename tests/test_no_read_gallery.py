import json
import tempfile
import unittest
from pathlib import Path

from tools.package_no_read_gallery import package


class NoReadGalleryTests(unittest.TestCase):
    def test_filter_order_embed_and_preserve_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'comparison').mkdir()
            for policy in ('broad', 'duplicate'):
                folder = root / 'result' / policy
                folder.mkdir(parents=True)
                (folder / 'crop.png').write_bytes(b'synthetic image bytes')
                rows, questions = [], []
                for number, code in ((10, '5'), (2, '5'), (1, '6')):
                    ident = f'C-p1-s0-q{number}'
                    crop_ids = [ident + '-r10', ident + '-r02']
                    rows.append(dict(id=ident, page=2, review=dict(status='보류', reasons=[dict(code=code, crop_ids=crop_ids)])))
                    questions.append(dict(id=ident, reasons=[dict(message='확인 <필요>')], evidence_images=[dict(id=i, path='crop.png') for i in ['context'] + crop_ids]))
                (root / 'comparison' / f'{policy}.json').write_text(json.dumps(dict(rows=rows)), encoding='utf-8')
                (folder / 'result.json').write_text(json.dumps(dict(questions=questions)), encoding='utf-8')
            output = root / 'gallery.html'
            package(root, output)
            text = output.read_text(encoding='utf-8')
            data = json.loads(text.split('const data=', 1)[1].split(';let index=0;', 1)[0])
            for rows in data['policies'].values():
                self.assertEqual([q['id'] for q in rows], ['C-p1-s0-q2', 'C-p1-s0-q10'])
                self.assertEqual([c['id'] for c in rows[0]['crops']], ['C-p1-s0-q2-r02', 'C-p1-s0-q2-r10'])
            self.assertEqual(len(data['assets']), 1)
            self.assertNotIn('확인 <필요>', text)
            with self.assertRaises(ValueError):
                package(root, output)


if __name__ == '__main__':
    unittest.main()
