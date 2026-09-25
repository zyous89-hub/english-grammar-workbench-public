import unittest

import cv2
import numpy as np

from tools.extract_added_ink import extract_added_ink, choice_preservation_mask
from tools.ocr_reference_filter import eligible_answer


class AddedInkTest(unittest.TestCase):
    def test_all_circled_lowercase_letters_are_preserved_but_plain_text_is_not(self):
        ref = np.full((80, 180), 255, np.uint8)
        cv2.circle(ref, (30, 35), 15, 0, 2)
        cv2.putText(ref, "c", (23, 42), cv2.FONT_HERSHEY_SIMPLEX, .6, 0, 2)
        cv2.putText(ref, "here", (90, 40), cv2.FONT_HERSHEY_SIMPLEX, .6, 0, 2)
        student = ref.copy()
        cv2.circle(student, (30, 35), 23, 80, 2)
        for symbol in map(chr, range(0x24D0, 0x24EA)):
            with self.subTest(symbol=symbol):
                mask, selected = choice_preservation_mask(ref.shape, [0, 0, 180, 80],
                    [{"symbol": symbol, "box": [14, 19, 46, 51]},
                     {"symbol": "c", "box": [90, 20, 170, 55]}])
                result, _ = extract_added_ink(student, ref, mask)
                self.assertEqual([x["symbol"] for x in selected], [symbol])
                np.testing.assert_array_equal(result[mask], student[mask])
                self.assertTrue(np.all(result[15:60, 85:175] == 255))
                self.assertEqual(int(result[35, 7]), 80)
                self.assertIsNone(eligible_answer(symbol, .99, "choice_mark_review"))

    def test_choice_exception_preserves_number_and_crossing_mark(self):
        ref = np.full((100, 200), 255, np.uint8)
        cv2.circle(ref, (40, 50), 10, 0, 2)
        cv2.putText(ref, "2", (35, 55), cv2.FONT_HERSHEY_SIMPLEX, .4, 0, 1)
        cv2.putText(ref, "here", (100, 50), cv2.FONT_HERSHEY_SIMPLEX, .7, 0, 2)
        student = ref.copy()
        cv2.circle(student, (40, 50), 18, 80, 2)
        mask, selected = choice_preservation_mask(student.shape, [0, 0, 200, 100],
            [{"symbol": "②", "box": [29, 39, 51, 61]}, {"symbol": "⑥", "box": [100, 30, 180, 60]}])
        result, _ = extract_added_ink(student, ref, mask)
        np.testing.assert_array_equal(result[mask], student[mask])
        self.assertTrue(np.all(result[25:60, 100:190] == 255))
        self.assertEqual(int(result[50, 22]), 80)
        self.assertEqual(len(selected), 1)
        self.assertIsNone(eligible_answer("②", .99, "choice_mark_review"))

    def test_nonoverlapping_choice_does_not_change_crop(self):
        a = np.full((20, 20), 255, np.uint8)
        mask, selected = choice_preservation_mask(a.shape, [0, 0, 20, 20],
            [{"symbol": "①", "box": [100, 100, 110, 110]}])
        self.assertFalse(mask.any())
        self.assertEqual(selected, [])
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
