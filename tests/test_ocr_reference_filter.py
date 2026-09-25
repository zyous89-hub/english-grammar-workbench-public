import unittest
import cv2
import numpy as np

from tools.ocr_reference_filter import reference_evidence, route_candidate, eligible_answer


class ReferenceRoutingTest(unittest.TestCase):
    def setUp(self):
        self.reference = np.full((100, 300), 215, np.uint8)
        self.reference[:, :30] = 255
        cv2.putText(self.reference, "123", (50, 55), cv2.FONT_HERSHEY_SIMPLEX, 1, 0, 2)

    def route(self, student, **kwargs):
        evidence, _ = reference_evidence(student, self.reference)
        return route_candidate(evidence, shaded=True, alignment_ok=True, **kwargs)

    def test_print_is_not_answer(self):
        self.assertEqual(self.route(self.reference.copy(), stage="print"), "reference_print")

    def test_mixed_handwriting_is_retained_for_review(self):
        student = self.reference.copy()
        cv2.line(student, (20, 80), (270, 70), 90, 2)
        before = student.copy()
        self.assertEqual(self.route(student), "mixed_print_review")
        np.testing.assert_array_equal(student, before)

    def test_white_gray_edge_has_no_answer(self):
        ref = np.full((100, 100), 215, np.uint8)
        ref[:, :40] = 255
        ev, _ = reference_evidence(ref, ref)
        self.assertEqual(route_candidate(ev, shaded=True, alignment_ok=True), "mixed_shade_background")
        self.assertEqual(route_candidate(ev, shaded=False, alignment_ok=True), "student_candidate")
        self.assertEqual(route_candidate(ev, shaded=True, alignment_ok=False), "alignment_review")

    def test_handwritten_number_on_white_survives(self):
        ref = np.full((100, 100), 255, np.uint8)
        student = ref.copy()
        cv2.putText(student, "3", (20, 65), cv2.FONT_HERSHEY_SIMPLEX, 1.5, 100, 2)
        ev, _ = reference_evidence(student, ref)
        self.assertEqual(route_candidate(ev, shaded=False, alignment_ok=True), "student_candidate")

    def test_no_digit_salvage_or_mixed_answer(self):
        self.assertEqual(eligible_answer("③", .8, "student_candidate"), [3])
        for text, score, route in [("abc2", .99, "student_candidate"), ("100", .99, "student_candidate"),
                                   ("3", .799, "student_candidate"), ("2", .99, "mixed_print_review")]:
            self.assertIsNone(eligible_answer(text, score, route))


if __name__ == "__main__":
    unittest.main()
