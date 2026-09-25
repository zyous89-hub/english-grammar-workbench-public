import unittest

import cv2
import numpy as np

from tools.extract_added_ink import extract_added_ink


class AddedInkTest(unittest.TestCase):
    def test_identical_print_is_empty(self):
        ref = np.full((100, 200), 220, np.uint8)
        cv2.putText(ref, "here", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)
        result, _ = extract_added_ink(ref.copy(), ref)
        self.assertTrue(np.all(result == 255))

    def test_only_added_stroke_pixels_survive(self):
        ref = np.full((100, 200), 255, np.uint8)
        cv2.line(ref, (80, 10), (80, 90), 0, 2)
        student = ref.copy()
        cv2.line(student, (10, 50), (180, 50), 60, 2)
        before = student.copy()
        result, _ = extract_added_ink(student, ref)
        self.assertEqual(int(result[50, 30]), 60)
        self.assertEqual(int(result[50, 80]), 255)  # Crossing ink deliberately removed too.
        self.assertEqual(int(result[30, 80]), 255)
        np.testing.assert_array_equal(student, before)


if __name__ == "__main__":
    unittest.main()
