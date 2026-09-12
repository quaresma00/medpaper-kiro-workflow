"""Tamper-evident PubMed verification receipts used by reference gates.

``verified: true`` is never accepted on its own.  A usable record must be bound to
the exact library file and to a cached raw XML payload produced by a fresh PubMed
EFetch request.  The gate reparses that payload and recomputes every material
bibliographic comparison.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree as ET


SCHEMA = 2
GENERATOR = "tools/pubmed/verify.py"
SOURCE = "ncbi_pubmed_efetch"
TITLE_THRESHOLD = 0.92
JOURNAL_THRESHOLD = 0.85
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CACHE_RE = re.compile(r"^06_refs/cache/verify_efetch_pubmed_[A-Za-z0-9_.-]+\.xml$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def norm(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9 ]", " ", text.casefold()).strip()


def ratio(left: object, right: object) -> float:
    a, b = norm(left), norm(right)
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def _text(node, path: str) -> str:
    found = node.find(path)
    return "" if found is None else "".join(found.itertext()).strip()


def _source_record(article) -> dict:
    pmid = _text(article, ".//MedlineCitation/PMID")
    title = _text(article, ".//Article/ArticleTitle") or _text(article, ".//BookTitle")
    abstract_parts = []
    for part in article.findall(".//Article/Abstract/AbstractText"):
        label = part.get("Label")
        body = "".join(part.itertext()).strip()
        if body:
            abstract_parts.append(f"{label}: {body}" if label else body)
    authors = []
    for author in article.findall(".//AuthorList/Author"):
        collective = _text(author, "CollectiveName")
        last = collective or _text(author, "LastName")
        if last:
            authors.append({"last": last, "first": _text(author, "ForeName")})
    year = _text(article, ".//Journal/JournalIssue/PubDate/Year")
    if not year:
        match = re.search(r"(?:19|20)\d{2}",
                          _text(article, ".//Journal/JournalIssue/PubDate/MedlineDate"))
        year = match.group(0) if match else ""
    # Identifiers are read only from the article's own metadata. A descendant search would also
    # sweep in the <ArticleIdList> of every cited reference under <ReferenceList>, which is how a
    # cited paper's PMCID ended up in library.json and got fetched as if it were the article.
    #
    # This duplicates the logic in tools/pubmed/eutils.py on purpose. This module exists to
    # re-derive the truth INDEPENDENTLY of the code that wrote library.json; sharing a parser
    # would mean a parser bug produced the same wrong value on both sides and the comparison
    # would agree with itself. Duplication here is the control, not an oversight.
    doi, pmcid = "", ""
    for path in ("./MedlineCitation/Article/ELocationID", "./BookDocument/Book/ELocationID"):
        for item in article.findall(path):
            if item.get("EIdType") == "doi" and not doi:
                doi = (item.text or "").strip()
    for path in ("./PubmedData/ArticleIdList", "./BookDocument/ArticleIdList",
                 "./PubmedBookData/ArticleIdList"):
        node = article.find(path)
        if node is None:
            continue
        for item in node.findall("ArticleId"):
            kind, value = item.get("IdType"), (item.text or "").strip()
            if not value:
                continue
            if kind == "doi" and not doi:
                doi = value
            elif kind == "pmc" and not pmcid:
                pmcid = value if value.upper().startswith("PMC") else f"PMC{value}"
    publication_types = [(item.text or "").strip()
                         for item in article.findall(".//PublicationTypeList/PublicationType")]
    corrections = [item.get("RefType", "") for item in
                   article.findall(".//CommentsCorrectionsList/CommentsCorrections")]
    flags = []
    if any("Retract" in item for item in publication_types) or "RetractionIn" in corrections:
        flags.append("RETRACTED_OR_RETRACTION")
    if "ExpressionOfConcernIn" in corrections:
        flags.append("EXPRESSION_OF_CONCERN")
    if "Preprint" in publication_types:
        flags.append("PREPRINT")
    return {
        "pmid": pmid,
        "doi": doi.casefold(),
        "pmcid": pmcid.upper(),
        "title": re.sub(r"\s+", " ", title).strip().rstrip("."),
        "journal": _text(article, ".//Journal/Title"),
        "year": year,
        "first_author": authors[0]["last"] if authors else "",
        "abstract": "\n".join(abstract_parts).strip(),
        "flags": flags,
    }


def parse_pubmed_payload(blob: bytes | str) -> dict[str, dict]:
    try:
        root = ET.fromstring(blob)
    except ET.ParseError as exc:
        raise ValueError(f"invalid PubMed XML: {exc}") from exc
    records: dict[str, dict] = {}
    for tag in ("PubmedArticle", "PubmedBookArticle"):
        for article in root.iter(tag):
            record = _source_record(article)
            if record["pmid"]:
                records[record["pmid"]] = record
    return records


def canonical_source(record: dict) -> dict:
    """The bibliographic identity that the receipt hash binds.

    PMCID is intentionally absent: it is where a copy can be downloaded, not who the paper is.
    Including it would change every existing receipt digest and invalidate verifications that
    are otherwise sound. compare_entry_to_source() checks it live instead.
    """
    return {
        "pmid": str(record.get("pmid", "")),
        "doi": str(record.get("doi", "")).strip().casefold(),
        "title": re.sub(r"\s+", " ", str(record.get("title", ""))).strip().rstrip("."),
        "journal": re.sub(r"\s+", " ", str(record.get("journal", ""))).strip(),
        "year": str(record.get("year", "")),
        "first_author": str(record.get("first_author") or
                            ((record.get("authors") or [{}])[0].get("last", ""))),
        "abstract": str(record.get("abstract", "")).strip(),
        "flags": sorted(str(item) for item in record.get("flags", [])),
    }


def record_sha256(record: dict) -> str:
    payload = json.dumps(canonical_source(record), sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def compare_entry_to_source(entry: dict, source: dict) -> list[str]:
    """Recompute all checks that determine whether a library entry is real."""
    # Read before canonicalising: PMCID is deliberately not part of canonical_source(), so it
    # has to come off the raw payload record.
    source_pmcid = str(source.get("pmcid", "")).strip().upper()
    source = canonical_source(source)
    problems = []
    if not re.fullmatch(r"\d+", str(entry.get("pmid", ""))):
        problems.append("library PMID is missing or non-numeric")
    elif str(entry.get("pmid")) != source["pmid"]:
        problems.append("PMID differs from PubMed payload")
    if ratio(entry.get("title", ""), source["title"]) < TITLE_THRESHOLD:
        problems.append("title differs from PubMed payload")
    if ratio(entry.get("journal", ""), source["journal"]) < JOURNAL_THRESHOLD:
        problems.append("journal differs from PubMed payload")
    if str(entry.get("year", "")) != source["year"]:
        problems.append("year differs from PubMed payload")
    first_author = ((entry.get("authors") or [{}])[0].get("last", ""))
    if norm(first_author) != norm(source["first_author"]):
        problems.append("first author differs from PubMed payload")
    if not source["abstract"]:
        problems.append("PubMed payload contains no abstract")
    entry_doi = str(entry.get("doi", "")).strip().casefold()
    if entry_doi != source["doi"]:
        problems.append("DOI differs from PubMed payload")
    # PMCID is a retrieval locator, not part of the citation, so it is deliberately NOT in
    # canonical_source() and does not participate in the receipt hash - adding it there would
    # invalidate every receipt already issued. It is compared live against the cached payload
    # instead, which is enough: a wrong PMCID sends fulltext.py to a different paper, and a
    # deep read of the wrong paper is worse than a missing one.
    entry_pmcid = str(entry.get("pmcid", "")).strip().upper()
    if entry_pmcid and entry_pmcid != source_pmcid:
        problems.append(
            f"PMCID differs from PubMed payload (library {entry_pmcid or '-'}, "
            f"payload {source_pmcid or 'none'}) - full text fetched with it is a different paper")
    if source["flags"]:
        problems.append("non-citable PubMed flag(s): " + ", ".join(source["flags"]))
    return problems


def evidence_for_live_record(record: dict) -> dict:
    return {
        "source": SOURCE,
        "cache_file": str(record.get("cache_file", "")),
        "payload_sha256": str(record.get("cache_sha256", "")),
        "record_sha256": record_sha256(record),
        "fresh_fetch": record.get("fresh_fetch") is True,
    }


def _load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return value


def _age_days(value: object) -> int | None:
    try:
        stamp = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00")).date()
    except (TypeError, ValueError):
        return None
    return (date.today() - stamp).days


def validate_local_proof(project: Path, required_keys: set[str] | None = None,
                         max_age_days: int = 90) -> tuple[bool, list[str], int]:
    """Validate a receipt without trusting any authored boolean or comparison result."""
    library_path = project / "06_refs/library.json"
    verified_path = project / "06_refs/verified.json"
    if not library_path.is_file() or not verified_path.is_file():
        missing = [str(path.relative_to(project)).replace("\\", "/") for path in
                   (library_path, verified_path) if not path.is_file()]
        return False, ["missing " + ", ".join(missing)], 0
    try:
        library = _load_json(library_path)
        verified = _load_json(verified_path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        return False, [f"reference verification files are invalid: {exc}"], 0

    entries = {str(item.get("citekey", "")): item for item in library.get("entries", [])
               if str(item.get("citekey", ""))}
    records = verified.get("records", {})
    if not isinstance(records, dict):
        records = {}
    problems: list[str] = []
    generator = verified.get("generator", {})
    if verified.get("schema") != SCHEMA:
        problems.append(f"verified.json schema must be {SCHEMA}; a boolean-only file is not evidence")
    if not isinstance(generator, dict) or generator.get("tool") != GENERATOR or \
            generator.get("mode") != "fresh_ncbi_pubmed_efetch":
        problems.append("verified.json lacks the bundled fresh-EFetch generator receipt")
    expected_library_hash = file_sha256(library_path)
    if verified.get("library_sha256") != expected_library_hash:
        problems.append("library.json changed after reference verification")
    age = _age_days(verified.get("verified_at"))
    if age is None or age < 0:
        problems.append("verified_at is missing or invalid")
    elif age > max_age_days:
        problems.append(f"reference verification is {age} days old (maximum {max_age_days})")
    if set(records) != set(entries):
        missing = sorted(set(entries) - set(records))
        extra = sorted(set(records) - set(entries))
        if missing:
            problems.append("verification receipt missing citekey(s): " + ", ".join(missing[:6]))
        if extra:
            problems.append("verification receipt has non-library citekey(s): " + ", ".join(extra[:6]))
    if verified.get("n_entries") != len(entries) or verified.get("n_verified") != len(entries):
        problems.append("verified.json summary counts do not equal the current library")

    wanted = set(entries) if required_keys is None else set(required_keys)
    unknown = sorted(wanted - set(entries))
    if unknown:
        problems.append("citekey(s) absent from library.json: " + ", ".join(unknown[:6]))
    payload_cache: dict[Path, tuple[str, dict[str, dict]]] = {}
    project_root = project.resolve()
    for key in sorted(wanted & set(entries)):
        receipt = records.get(key)
        if not isinstance(receipt, dict) or receipt.get("verified") is not True:
            problems.append(f"{key}: verified=true receipt is absent")
            continue
        evidence = receipt.get("evidence", {})
        if not isinstance(evidence, dict) or evidence.get("source") != SOURCE or \
                evidence.get("fresh_fetch") is not True:
            problems.append(f"{key}: no fresh NCBI PubMed EFetch evidence")
            continue
        rel = str(evidence.get("cache_file", "")).replace("\\", "/")
        if not CACHE_RE.fullmatch(rel):
            problems.append(f"{key}: verification cache path is not a bundled verifier output")
            continue
        cache_path = (project / rel).resolve()
        try:
            cache_path.relative_to(project_root)
        except ValueError:
            problems.append(f"{key}: verification cache escapes the project")
            continue
        if not cache_path.is_file():
            problems.append(f"{key}: verification payload is missing: {rel}")
            continue
        if cache_path not in payload_cache:
            try:
                digest = file_sha256(cache_path)
                payload_cache[cache_path] = (digest, parse_pubmed_payload(cache_path.read_bytes()))
            except (OSError, ValueError) as exc:
                problems.append(f"{key}: cannot parse verification payload ({exc})")
                continue
        digest, source_records = payload_cache[cache_path]
        claimed = str(evidence.get("payload_sha256", "")).casefold()
        if not SHA_RE.fullmatch(claimed) or claimed != digest:
            problems.append(f"{key}: PubMed payload hash mismatch")
            continue
        pmid = str(entries[key].get("pmid", ""))
        source = source_records.get(pmid)
        if source is None:
            problems.append(f"{key}: PMID {pmid or '(missing)'} is absent from its PubMed payload")
            continue
        source_hash = record_sha256(source)
        if evidence.get("record_sha256") != source_hash:
            problems.append(f"{key}: parsed PubMed record fingerprint mismatch")
        for issue in compare_entry_to_source(entries[key], source):
            problems.append(f"{key}: {issue}")
        if str(receipt.get("pmid", "")) != source["pmid"]:
            problems.append(f"{key}: receipt PMID differs from its PubMed payload")
        if str(receipt.get("doi", "")).strip().casefold() != source["doi"]:
            problems.append(f"{key}: receipt DOI differs from its PubMed payload")
    return not problems, problems, len(wanted & set(entries))

