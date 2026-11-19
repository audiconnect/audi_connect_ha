"""Keep living documentation independent of release snapshots."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD_REFERENCE = re.compile(
    r"\b(?:b\d{1,3}|rc\d+|\d+\.\d+\.\d+(?:b|rc)\d+)\b", re.IGNORECASE
)
RELATIVE_LINK = re.compile(r"\]\(([^)\s]+)\)")


def living_documents():
    """Use all maintained guides and issue templates, not release notes."""
    paths = list((ROOT / "docs").rglob("*.md"))
    paths.extend(ROOT.glob("*.md"))
    paths.extend((ROOT / ".github").rglob("*.md"))
    return [
        path
        for path in sorted(paths)
        if path.relative_to(ROOT).as_posix() != "docs/HACS_CANDIDATE.md"
    ]


def test_living_documentation_has_no_candidate_versions():
    """Versioned evidence belongs in releases, issues and Git history."""
    offenders = []
    for path in living_documents():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if BUILD_REFERENCE.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, "\n".join(offenders)


def test_living_documentation_relative_links_exist():
    """Do not leave links to deleted or moved repository files."""
    offenders = []
    for path in living_documents():
        for target in RELATIVE_LINK.findall(path.read_text(encoding="utf-8")):
            if target.startswith(("#", "http:", "https:", "mailto:")):
                continue
            if not (path.parent / target.split("#", 1)[0]).exists():
                offenders.append(f"{path.relative_to(ROOT)}: {target}")
    assert not offenders, "\n".join(offenders)


def test_public_guides_do_not_reference_internal_delivery():
    """Keep fork-specific delivery status out of user and research guides."""
    internal = re.compile(
        r"npinguin/audi_connect_ha/issues/(?:35|36|44)\b"
        r"|audiconnect/audi_connect_ha/pull/918\b"
        r"|feature/v3-upstream-review|V3_FEATURE_CLOSURE\.md"
        r"|(?:stable gate|release HOLD|exact-head CI|active backlog)",
        re.IGNORECASE,
    )
    offenders = []
    for path in living_documents():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if internal.search(line):
                offenders.append(f"{path.relative_to(ROOT)}:{number}")
    assert not offenders, "\n".join(offenders)
