"""The policy corpus: versioned Markdown documents made of clauses.

Each file is one complete version of one document. Front matter gives the
document id, office, version and the date the version comes into force. A
clause is a level-2 heading that starts with a clause id (``## LB-3.2 Title``).
A version stays in force until the next version of the same document starts.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import yaml

CLAUSE_HEADING = re.compile(r"^##\s+([A-Z]{2}-\d+\.\d+)\s+(.+?)\s*$")
REPLACES_LINE = re.compile(r"^Replaces:\s*([A-Z]{2}-\d+\.\d+)\s*$")


class PolicyFormatError(ValueError):
    pass


@dataclass(frozen=True)
class Clause:
    id: str
    title: str
    text: str
    replaces: str | None = None


@dataclass
class PolicyVersion:
    document: str
    title: str
    office: str
    version: str
    effective_from: date
    clauses: dict[str, Clause] = field(default_factory=dict)
    source: str = ""

    def to_dict(self) -> dict:
        return {
            "document": self.document,
            "title": self.title,
            "office": self.office,
            "version": self.version,
            "effective_from": self.effective_from.isoformat(),
            "source": self.source,
            "clauses": [
                {"id": c.id, "title": c.title, "text": c.text, "replaces": c.replaces}
                for c in self.clauses.values()
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "PolicyVersion":
        clauses = {
            c["id"]: Clause(c["id"], c["title"], c["text"], c.get("replaces"))
            for c in d["clauses"]
        }
        return cls(
            document=d["document"],
            title=d["title"],
            office=d["office"],
            version=str(d["version"]),
            effective_from=date.fromisoformat(d["effective_from"]),
            clauses=clauses,
            source=d.get("source", ""),
        )


@dataclass(frozen=True)
class Retirement:
    """Where a clause stopped being in force, and what replaced it."""

    clause: str
    retired_in: str  # version that no longer contains the clause
    retired_from: date
    replaced_by: str | None


def parse_policy(text: str, source: str = "") -> PolicyVersion:
    if not text.startswith("---"):
        raise PolicyFormatError(f"{source}: missing front matter")
    try:
        _, front, body = text.split("---", 2)
    except ValueError as exc:
        raise PolicyFormatError(f"{source}: unterminated front matter") from exc
    meta = yaml.safe_load(front) or {}
    for key in ("document", "title", "office", "version", "effective_from"):
        if key not in meta:
            raise PolicyFormatError(f"{source}: front matter needs '{key}'")
    eff = meta["effective_from"]
    if isinstance(eff, str):
        eff = date.fromisoformat(eff)

    clauses: dict[str, Clause] = {}
    current: list | None = None  # [id, title, lines, replaces]

    def flush() -> None:
        if current is None:
            return
        cid, title, lines, replaces = current
        if cid in clauses:
            raise PolicyFormatError(f"{source}: clause {cid} appears twice")
        clauses[cid] = Clause(cid, title, " ".join(" ".join(lines).split()), replaces)

    for line in body.splitlines():
        m = CLAUSE_HEADING.match(line)
        if m:
            flush()
            current = [m.group(1), m.group(2), [], None]
            continue
        if line.startswith("#"):
            flush()
            current = None
            continue
        if current is None:
            continue
        r = REPLACES_LINE.match(line.strip())
        if r:
            current[3] = r.group(1)
        else:
            current[2].append(line.strip())
    flush()
    if not clauses:
        raise PolicyFormatError(f"{source}: no clauses found")
    return PolicyVersion(
        document=str(meta["document"]),
        title=str(meta["title"]),
        office=str(meta["office"]),
        version=str(meta["version"]),
        effective_from=eff,
        clauses=clauses,
        source=source,
    )


class Corpus:
    """All versions of all policy documents."""

    def __init__(self, versions: list[PolicyVersion]):
        self.versions = sorted(versions, key=lambda v: (v.document, v.effective_from))
        seen = set()
        for v in self.versions:
            key = (v.document, v.version)
            if key in seen:
                raise PolicyFormatError(f"{v.document} v{v.version} defined twice")
            seen.add(key)

    @classmethod
    def load(cls, root: str | Path) -> "Corpus":
        root = Path(root)
        files = sorted(root.rglob("*.md"))
        if not files:
            raise PolicyFormatError(f"no policy files under {root}")
        versions = [
            parse_policy(f.read_text(encoding="utf-8"), f.relative_to(root).as_posix())
            for f in files
        ]
        corpus = cls(versions)
        corpus._fingerprint = _hash_files(files, root)
        return corpus

    @classmethod
    def from_snapshot(cls, data: dict) -> "Corpus":
        corpus = cls([PolicyVersion.from_dict(v) for v in data["versions"]])
        corpus._fingerprint = data.get("corpus_fingerprint", "")
        return corpus

    def to_snapshot(self) -> dict:
        return {
            "corpus_fingerprint": self.fingerprint,
            "versions": [v.to_dict() for v in self.versions],
        }

    @property
    def fingerprint(self) -> str:
        return getattr(self, "_fingerprint", "")

    def documents(self) -> list[str]:
        return sorted({v.document for v in self.versions})

    def offices(self) -> list[str]:
        return sorted({v.office for v in self.versions})

    def document_for_office(self, office: str) -> str | None:
        docs = {v.document for v in self.versions if v.office == office}
        return next(iter(docs)) if len(docs) == 1 else None

    def history(self, document: str) -> list[PolicyVersion]:
        return [v for v in self.versions if v.document == document]

    def get(self, document: str, version: str) -> PolicyVersion | None:
        for v in self.versions:
            if v.document == document and v.version == version:
                return v
        return None

    def version_in_force(self, document: str, on: date) -> PolicyVersion | None:
        """The latest version whose effective date is on or before ``on``."""
        current = None
        for v in self.history(document):
            if v.effective_from <= on:
                current = v
        return current

    def retirement(self, document: str, clause_id: str) -> Retirement | None:
        """The first version after the clause existed that no longer has it."""
        existed = False
        for v in self.history(document):
            if clause_id in v.clauses:
                existed = True
            elif existed:
                replaced_by = next(
                    (c.id for c in v.clauses.values() if c.replaces == clause_id), None
                )
                return Retirement(clause_id, v.version, v.effective_from, replaced_by)
        return None


def _hash_files(files: list[Path], root: Path) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f.relative_to(root).as_posix().encode())
        h.update(f.read_bytes().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:12]
