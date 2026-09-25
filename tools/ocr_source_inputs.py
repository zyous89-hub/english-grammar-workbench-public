"""Explicit local inputs for source preparation; never guess a PDF by name."""
import argparse
import json
from pathlib import Path


def read_inputs(argv=None):
    parser = argparse.ArgumentParser(description="학생 폴더·원본 PDF·답지 PDF 직접 지정")
    parser.add_argument("--student-dir", required=True, type=Path)
    parser.add_argument("--original", required=True, type=Path)
    parser.add_argument("--answer-key", required=True, type=Path)
    parser.add_argument("--key-first-page", required=True, type=int,
                        help="답지 PDF에서 정답이 시작되는 실제 페이지 번호 (1부터)")
    parser.add_argument("--config", required=True, type=Path,
                        help="기존 페이지/문항 매핑 JSON; 아직 자동 매핑하지 않음")
    parser.add_argument("--set-id", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    for name in ("student_dir", "original", "answer_key", "config", "output"):
        setattr(args, name, getattr(args, name).resolve())
    if not args.student_dir.is_dir():
        parser.error("학생 폴더가 없습니다")
    for name in ("original", "answer_key", "config"):
        if not getattr(args, name).is_file():
            parser.error(f"지정한 파일이 없습니다: {name}")
    if args.original.suffix.lower() != ".pdf" or args.answer_key.suffix.lower() != ".pdf":
        parser.error("현재 원본과 답지 입력은 PDF만 지원합니다")
    if args.key_first_page < 1:
        parser.error("답지 시작 페이지는 1 이상이어야 합니다")
    if args.output.exists():
        parser.error("출력 폴더가 이미 있습니다. 새 폴더를 지정하세요")
    configs = json.loads(args.config.read_text(encoding="utf-8-sig"))
    selected = [c for c in configs if c["id"] == args.set_id]
    if len(selected) != 1:
        parser.error("설정에서 지정한 세트를 정확히 하나 찾을 수 없습니다")
    return args, selected


def answer_key_text(document, first_page):
    """Read only the explicitly selected answer document, using 1-based pages."""
    if not 1 <= first_page <= len(document):
        raise ValueError("답지 시작 페이지가 지정한 PDF 범위를 벗어납니다")
    return "\n".join(document[i].get_textpage().get_text_range()
                     for i in range(first_page - 1, len(document)))
