import unittest
import cv2
import numpy as np

from tools.build_repair_gallery import gray_residue, crossed_components


class RepairGalleryTests(unittest.TestCase):
    def test_gray_band_and_boundary_are_diagnostic_candidates(self):
        reference = np.full((40, 120), 255, np.uint8)
        reference[10:30] = 215
        student = reference.copy()
        student[14:17] = 120
        self.assertTrue(gray_residue(student, reference)['candidate'])
        self.assertFalse(gray_residue(student, np.full_like(reference, 255))['candidate'])
        mask = np.zeros((80, 80), np.uint8)
        mask[20:60, 30:34] = 1
        _, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
        self.assertEqual(crossed_components(labels, stats, [25, 15, 40, 40], [0, 0, 80, 40]), [(1, 40, 1)])
        self.assertFalse(crossed_components(labels, stats, [25, 15, 40, 35], [0, 0, 80, 40]))


if __name__ == '__main__':
    unittest.main()
