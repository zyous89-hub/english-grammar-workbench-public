import base64
import json
from pathlib import Path
import tempfile
import unittest

from tools.package_comparison_report import package


class PortableReportTest(unittest.TestCase):
    def test_images_are_shared_and_navigation_stays_inside(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            image=b'original image bytes'
            (root/'crop.png').write_bytes(image)
            source='<p>한글</p><img src="crop.png"><a href="broad.html">상세</a>'
            for name in ('report.html','broad.html','duplicate.html'):
                (root/name).write_text(source,encoding='utf-8')
            output=root/'portable.html'
            package(root,output)
            text=output.read_text(encoding='utf-8')
            data=json.loads(text.split('const data=',1)[1].split(';const frame=',1)[0])
            self.assertEqual(len(data['images']),1)
            self.assertEqual(base64.b64decode(data['images']['image0'].split(',')[1]),image)
            self.assertEqual(len(data['reports']),3)
            for report in data['reports'].values():
                self.assertIn('한글',report)
                self.assertIn('data-asset="image0"',report)
                self.assertIn("parent.showReport('broad')",report)
                self.assertNotIn('src="crop.png"',report)
            with self.assertRaises(ValueError):
                package(root,output)
