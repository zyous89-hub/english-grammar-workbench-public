import unittest
from tools.classify_grid_stages import question_review
from tests import test_stage_classification as stage_tests


class ScanResolutionTest(unittest.TestCase):
    def test_scan_resolution_guard_preserves_readings_and_blocks_every_question(self):
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from PIL import Image
        from tools.scan_resolution import inspect_scan_sizes

        alignment = dict(matrix=[[1]], inliers=31, median_error=3)
        helper = stage_tests.StageClassificationTest()
        questions = [[helper.crop()], [helper.crop(score=.2)], []]
        baseline = [question_review(rows, '③', alignment) for rows in questions]
        with TemporaryDirectory() as folder:
            source = Path(folder); (source/'sources').mkdir()
            scan = source/'sources/scan.png'
            for short_side in (1654, 2399, 2400, 2480, 2560, 2561):
                for rotated in (False, True):
                    with self.subTest(short_side=short_side, rotated=rotated):
                        size = (3507, short_side) if rotated else (short_side, 3507)
                        Image.new('L', size, 255).save(scan)
                        digest = hashlib.sha256(scan.read_bytes()).hexdigest()
                        # Old metadata can be stale: inspect the frozen extraction copy.
                        original = dict(alignment, source=str(source/'missing/scan.png'), scan_short_side=2480)
                        page, = inspect_scan_sizes([original], source)
                        self.assertEqual(original['scan_short_side'], 2480)
                        self.assertEqual(page['scan_short_side'], short_side)
                        for rows, before in zip(questions, baseline):
                            after = question_review(rows, '③', page)
                            if 2400 <= short_side <= 2560:
                                self.assertEqual(after, before)
                            else:
                                self.assertEqual(after['status'], '보류')
                                self.assertIsNone(after['selection'])
                                self.assertEqual(after['proposed_selection'], before['proposed_selection'])
                                self.assertEqual(after['candidates'], before['candidates'])
                                self.assertEqual(after['reasons'][:-1], before['reasons'])
                                self.assertEqual(after['reasons'][-1], dict(stage=1, code='17',
                                    rule='scan_resolution', crop_ids=[], message=
                                    f'스캔 해상도 확인 필요: 300dpi로 스캔해 주세요 (현재 짧은 변 {short_side} px)'))
                        self.assertEqual(hashlib.sha256(scan.read_bytes()).hexdigest(), digest)
                        with Image.open(scan) as image:
                            self.assertEqual(image.size, size)
            with self.assertRaises(FileNotFoundError):
                inspect_scan_sizes([dict(source=str(source/'missing.jpg'))], source)


if __name__ == '__main__':
    unittest.main()
