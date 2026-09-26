"""B08 synthetic selection regression; no OCR or student data is used.

Run: python -m unittest tests.test_b08_candidate_conflict
This checks existing selection behavior, not the pending stage/reason schema.
"""
import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from tools.grade_added_ink import grade


class B08CandidateConflictTest(unittest.TestCase):
    def test_all_candidates_count_regardless_of_region_order(self):
        # ponytail: synthetic OCR output isolates selection; OCR accuracy is separate.
        cases = [
            ([("r01", "1", .99), ("r99", "3", .90)], None),
            ([("r99", "3", .90), ("r01", "1", .99)], None),
            ([("r99", "1", .90), ("r01", "3", .99)], None),
            ([("r01", "3", .99), ("r99", "1", .90)], None),
            ([("r01", "3", .90), ("r99", "3", .99)], [3]),
            ([("r01", "1,3", .99)], [1, 3]),
            ([("r01", "1,3", .99), ("r99", "3,1", .90)], [1, 3]),
            ([("r01", "1,3", .99), ("r99", "3", .90)], None),
            # Known limitation: a rejected/absent fragment cannot cause a conflict.
            ([("r01", "1", .79), ("r99", "3", .99)], [3]),
            ([("r99", "3", .99)], [3]),
        ]
        with tempfile.TemporaryDirectory(prefix="b08-check-") as folder:
            root = Path(folder)
            source, output = root / "source", root / "output"
            source.mkdir()
            output.mkdir()
            image = root / "synthetic.png"
            image.write_bytes(base64.b64decode(
                "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aP4sAAAAASUVORK5CYII="))
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            questions, rows, previous = [], [], []
            for n, (fragments, _) in enumerate(cases, 1):
                qid = f"synthetic-q{n}"
                questions.append(dict(id=qid, page=1, key={"answer": "3"},
                                      context=str(image), segments=[f"{qid}-{r}" for r, _, _ in fragments]))
                previous.append(dict(id=qid, status="보류", selection=None))
                for rid, text, score in fragments:
                    rows.append(dict(id=f"{qid}-{rid}", question_id=qid, text=text, score=score,
                                     route="student_candidate", semantic_annotation=None,
                                     input=str(image), input_sha256=digest, ignored=False))

            def save(path, value):
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")

            save(source / "questions.json", questions)
            save(source / "pages.json", [{"page": 1}])
            save(output / "results.json", rows)
            save(output / "timing.json", {"ocr_executed": 0})
            save(root / "previous.json", previous)
            save(root / "review.json", {"rows": []})
            with contextlib.redirect_stdout(io.StringIO()):
                grade(source, output, root / "previous.json", root / "review.json")
            actual = json.loads((output / "evaluation.json").read_text(encoding="utf-8"))
            self.assertEqual(len(actual), len(cases))
            for row, (_, expected) in zip(actual, cases):
                with self.subTest(question=row["id"]):
                    self.assertEqual(row["selection"], expected)
                    status = "보류" if expected is None else "정답" if expected == [3] else "오답"
                    self.assertEqual(row["status"], status)


if __name__ == "__main__":
    unittest.main()
