import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tools.ocr_source_inputs import read_inputs, answer_key_text


class SourceInputsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "학생").mkdir()
        for name in ("chosen.pdf", "key.pdf", "Grammar Build Up.pdf"):
            (self.root / name).write_bytes(b"fixture")
        (self.root / "config.json").write_text(json.dumps([{"id": "X"}]))
        self.argv = ["--student-dir", str(self.root / "학생"),
                     "--original", str(self.root / "chosen.pdf"),
                     "--answer-key", str(self.root / "key.pdf"),
                     "--key-first-page", "1", "--set-id", "X",
                     "--config", str(self.root / "config.json"),
                     "--output", str(self.root / "new")]

    def test_exact_files_and_non_c_set_selected_without_name_guessing(self):
        args, configs = read_inputs(self.argv)
        self.assertEqual(args.original, self.root / "chosen.pdf")
        self.assertEqual(args.answer_key, self.root / "key.pdf")
        self.assertEqual(configs, [{"id": "X"}])
        self.assertFalse(args.output.exists())

    def test_missing_explicit_original_does_not_fall_back_to_other_pdf(self):
        (self.root / "chosen.pdf").unlink()
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            read_inputs(self.argv)

    def test_same_pdf_can_be_explicitly_selected_for_both_roles(self):
        self.argv[self.argv.index("--answer-key") + 1] = str(self.root / "chosen.pdf")
        args, _ = read_inputs(self.argv)
        self.assertEqual(args.original, args.answer_key)

    def test_existing_output_and_unknown_set_are_rejected(self):
        for flag, value in (("--output", str(self.root)), ("--set-id", "missing"),
                            ("--key-first-page", "0")):
            argv = self.argv.copy()
            argv[argv.index(flag) + 1] = value
            with self.subTest(flag=flag), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                read_inputs(argv)

    def test_key_page_range_reads_selected_document_only(self):
        pages = [Mock(), Mock(), Mock()]
        for page, text in zip(pages, ("cover", "key one", "key two")):
            page.get_textpage.return_value.get_text_range.return_value = text
        self.assertEqual(answer_key_text(pages, 2), "key one\nkey two")
        pages[0].get_textpage.assert_not_called()
        for invalid in (0, 4):
            with self.assertRaises(ValueError):
                answer_key_text(pages, invalid)


if __name__ == "__main__":
    unittest.main()
