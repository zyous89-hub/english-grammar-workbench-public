"""Build the offline review form from the audited rule inventory (no student data)."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[1]


def build():
    source = ROOT / "docs/ocr-rule-inventory-079.md"
    raw = source.read_text(encoding="utf-8")
    rules, category = [], ""
    for line in raw.splitlines():
        if re.match(r"## [A-G]\. ", line):
            category = line[3:]
        match = re.fullmatch(r"\| ([A-G]\d{2}) \| (.*?) \| (.*?) \|", line)
        if match:
            rid, rule, origin = match.groups()
            rules.append(dict(id=rid, category=category, rule=rule, origin=origin))
    assert len(rules) == len({r["id"] for r in rules}) == 72
    extra = raw[raw.index("## H."):]
    data = dict(version="079", source="docs/ocr-rule-inventory-079.md",
                source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                rules=rules, additional_notes=extra)
    template = (ROOT / "tools/templates/ocr-rule-review.html").read_text(encoding="utf-8")
    output = template.replace("__RULE_DATA__", json.dumps(data, ensure_ascii=False).replace("<", "\\u003c"))
    target = ROOT / "docs/ocr-rule-review.html"
    target.write_text(output, encoding="utf-8")
    print(f"Built {len(rules)} rules: {target}")


if __name__ == "__main__":
    build()
