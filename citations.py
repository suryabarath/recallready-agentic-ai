"""Local citation checks, independent of the proposed A1 output schema."""

import re

from source import Evidence, Source, SourceError


class CitationError(ValueError):
    """A citation or literal value is unsupported by exact source evidence."""


def validate_citation(source: Source, citation: Evidence, *, recall_number: str,
                      event_id: str, snapshot_id: str) -> Evidence:
    """Resolve against selected source, then compare every provenance/text field."""
    if not isinstance(citation, Evidence):
        raise CitationError("Expected an Evidence citation")
    try:
        expected = source.resolve(citation.evidence_id, recall_number=recall_number,
                                  event_id=event_id, snapshot_id=snapshot_id)
    except SourceError as exc:
        raise CitationError(str(exc)) from exc
    if citation != expected:
        raise CitationError("Citation provenance or original text differs from source")
    return expected


def validate_literal_identifier(source: Source, value: str, evidence_ids: list[str], *,
                                recall_number: str, event_id: str,
                                snapshot_id: str) -> tuple[Evidence, ...]:
    """Check a literal against every cited passage, without interpreting its kind.

    Case, spaces, punctuation and leading zeros are significant. Disallow partial
    words/codes/dates, including hyphen/slash/dot-connected segments. Sentence
    punctuation may follow a complete value. Only product/code fields support
    identifier literals. This does not establish semantic kind or scope.
    """
    if not isinstance(value, str) or not value.strip():
        raise CitationError("Identifier must be a nonblank string")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise CitationError("Identifier requires evidence IDs")
    pattern = re.compile(r"(?<![\w/\-])(?<!\w\.)" + re.escape(value) + r"(?![\w/\-]|\.\w)")
    resolved = []
    for evidence_id in evidence_ids:
        try:
            e = source.resolve(evidence_id, recall_number=recall_number,
                               event_id=event_id, snapshot_id=snapshot_id)
        except SourceError as exc:
            raise CitationError(str(exc)) from exc
        if e.field_name not in ("product_description", "code_info") or not pattern.search(e.original_text):
            raise CitationError(f"Unsupported literal identifier {value!r} in {evidence_id}")
        resolved.append(e)
    return tuple(resolved)
