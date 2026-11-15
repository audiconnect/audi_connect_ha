"""Keep living documentation independent of release snapshots."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_REFERENCE = re.compile(
    r"\b(?:b\d{1,3}|rc\d+|\d+\.\d+\.\d+(?:b|rc)\d+)\b", re.IGNORECASE
)


def test_living_documentation_has_no_candidate_versions():
    """Versioned evidence belongs in releases, issues and Git history."""
    paths = list((ROOT / "docs").rglob("*.md"))
    paths.extend(ROOT.glob("*.md"))
    offenders = []
    for path in sorted(paths):
        if path.relative_to(ROOT).as_posix() == "docs/HACS_CANDIDATE.md":
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if BUILD_REFERENCE.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, "\n".join(offenders)
