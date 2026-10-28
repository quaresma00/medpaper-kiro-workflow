"""Machine-verifiable proof that acquisition covered the protocol-defined universe.

The workflow cannot prove what exists in every external database, but it can require the
external total-count receipt, exhaust pagination, recount the received raw payloads, bind
the proof to their hashes, and reject convenience sampling in acquisition code.  That is a
materially stronger contract than treating the presence of one raw file as "data acquired".
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

SCHEMA_VERSION = 1
MANIFEST_REL = "02_data/acquisition_manifest.json"
SUMMARY_REL = "03_analysis/results/dataset_summary.json"
FULL_SCOPE = "full_protocol_defined_universe"
COMPLETE = "complete"
LIMITED = "source_limited_user_authorized"

_SOURCE_TYPES = {
    "api", "database", "file", "instrument", "registry", "repository",
    "user_provided", "other",
}
_METHODS = {"scripted", "manual", "user_provided"}
_TEXT_CODE_SUFFIXES = {".py", ".r", ".sql", ".ps1", ".sh", ".js", ".ts", ".ipynb"}
_PLACEHOLDER = re.compile(r"(?i)(?:^|\b)(?:todo|tbd|unknown|example|placeholder)(?:\b|$)|[<>]")
_CONVENIENCE_REASON = re.compile(
    r"(?i)save time|faster|quick(?:er)?|convenien|token|context window|too (?:large|big)|"
    r"compute budget|avoid downloading|first \d+|random subset|representative subset"
)

# These constructs are not always wrong in isolation, so two explicit annotations exist:
# MEDPAPER_PILOT_ONLY and MEDPAPER_PROTOCOL_SAMPLING.  Both are checked against the manifest.
_CAP_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("SQL LIMIT", re.compile(r"(?i)\blimit\s+\d+\b")),
    ("SQL TOP", re.compile(r"(?i)\bselect\s+top\s*(?:\(\s*)?\d+")),
    ("SQL TABLESAMPLE", re.compile(r"(?i)\btablesample\b")),
    ("SQL FETCH FIRST", re.compile(r"(?i)\bfetch\s+first\s+\d+")),
    ("head/take", re.compile(r"(?i)(?:\.\s*head|\bhead|\.\s*take|\bslice_head)\s*\(")),
    ("sampling call", re.compile(r"(?i)(?:\.\s*sample|\brandom\.sample|\bsample_n|\bsample_frac)\s*\(")),
    ("reader row cap", re.compile(r"(?i)\bnrows\s*=|\b(?:max|row|record)_(?:rows?|records?|items?|results?|pages?)\s*=")),
    ("fixed leading slice", re.compile(r"\[\s*:\s*\d+\s*\]")),
    ("shell first rows", re.compile(r"(?i)\|\s*head\b|select-object\s+-first\b")),
    ("command result cap", re.compile(r"(?i)--(?:max-records?|row-limit|record-limit)\b")),
)


@dataclass
class Validation:
    ok: bool
    problems: list[str]
    sources: int = 0
    records_received: int = 0
    raw_files: int = 0
    bundle_sha256: str = ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_rel(value: object, prefix: str) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("\\", "/")
    pure = PurePosixPath(text)
    if pure.is_absolute() or ".." in pure.parts or not text.startswith(prefix.rstrip("/") + "/"):
        return None
    return pure.as_posix()


def inventory(project: Path, base_rel: str) -> list[dict]:
    from . import datasources
    base = project / base_rel
    if not base.exists():
        return []
    found: list[dict] = []
    for path in sorted(p for p in base.rglob("*") if p.is_file() and p.name != ".gitkeep"):
        rel = path.relative_to(project).as_posix()
        size = path.stat().st_size
        # 1.13.0: hashes cached by size + mtime - the gate no longer re-reads GBs on every run
        found.append({"path": rel, "sha256": datasources.cached_sha256(project, path),
                      "bytes": size})
    return found


def raw_inventory(project: Path) -> list[dict]:
    """1.13.0: downloaded payloads in 02_data/raw/ plus the declared data sources, which stay
    in place (`datasource:<name>/<file>` labels) and are never copied into the paper."""
    from . import datasources
    return sorted(inventory(project, "02_data/raw") + datasources.inventory(project),
                  key=lambda x: x["path"])


def _evidence_file(project: Path, raw: object, raw_paths: set[str]) -> tuple[str, Path]:
    from . import datasources
    if isinstance(raw, str) and raw.startswith(datasources.LABEL_PREFIX):
        path = datasources.resolve(project, raw) if raw in raw_paths else None
        if path is None:
            raise ValueError("evidence path must name a declared data-source file "
                             "(datasource:<name>/<file>) or an inventoried file under 02_data/raw/")
        return raw, path
    rel = _safe_rel(raw, "02_data/raw")
    if not rel or rel not in raw_paths:
        raise ValueError("evidence path must name an inventoried file under 02_data/raw/ or a "
                         "declared data-source file (datasource:<name>/<file>)")
    return rel, project / rel


def _zip_member(path: Path, spec: dict):
    import io
    import zipfile
    member = spec.get("member")
    if not isinstance(member, str) or not member:
        raise ValueError("zip_member_* evidence needs a 'member' (path inside the archive)")
    zf = zipfile.ZipFile(path)
    try:
        names = {n.casefold(): n for n in zf.namelist()}
        name = names.get(member.casefold())
        if name is None:
            raise ValueError(f"{member} is not in {path.name}")
        raw = zf.open(name)
        return zf, io.TextIOWrapper(raw, encoding=spec.get("encoding", "utf-8"),
                                    errors=spec.get("errors", "strict"), newline="")
    except Exception:
        zf.close()
        raise


def bundle_sha256(entries: list[dict]) -> str:
    digest = hashlib.sha256()
    for item in sorted(entries, key=lambda x: str(x.get("path", ""))):
        digest.update(
            f"{item.get('path', '')}\t{item.get('sha256', '')}\t{item.get('bytes', '')}\n".encode("utf-8")
        )
    return digest.hexdigest()


def _integer(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _aware_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _json_pointer(payload: object, pointer: str) -> object:
    if pointer == "":
        return payload
    if not pointer.startswith("/"):
        raise ValueError("JSON pointer must start with /")
    value = payload
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            value = value[int(token)]
        elif isinstance(value, dict):
            value = value[token]
        else:
            raise ValueError(f"cannot descend through {type(value).__name__}")
    return value


def evidence_count(project: Path, spec: object, raw_paths: set[str]) -> int:
    if not isinstance(spec, dict):
        raise ValueError("evidence must be an object")
    rel, path = _evidence_file(project, spec.get("path"), raw_paths)
    kind = spec.get("kind")
    if kind in ("zip_member_rows", "zip_member_lines"):
        # 1.13.0: archives are read by streaming one member - never extracted or copied.
        zf, handle = _zip_member(path, spec)
        try:
            if kind == "zip_member_lines":
                count = sum(1 for line in handle if line.strip())
            else:
                delimiter = spec.get("delimiter", ",")
                if not isinstance(delimiter, str) or len(delimiter) != 1:
                    raise ValueError("zip_member_rows delimiter must be one character")
                quoting = csv.QUOTE_NONE if spec.get("quoting") == "none" else csv.QUOTE_MINIMAL
                count = sum(1 for _ in csv.reader(handle, delimiter=delimiter, quoting=quoting))
        finally:
            handle.close()
            zf.close()
        if spec.get("header", True) and count:
            count -= 1
        return count
    if kind == "delimited_rows":
        delimiter = spec.get("delimiter")
        if delimiter is None:
            delimiter = "\t" if path.suffix.lower() in {".tsv", ".tab"} else ","
        if not isinstance(delimiter, str) or len(delimiter) != 1:
            raise ValueError("delimited_rows delimiter must be one character")
        with path.open("r", encoding=spec.get("encoding", "utf-8-sig"), newline="") as handle:
            count = sum(1 for _ in csv.reader(handle, delimiter=delimiter))
        if spec.get("header", True) and count:
            count -= 1
        return count
    if kind == "jsonl_rows":
        with path.open("r", encoding=spec.get("encoding", "utf-8"), errors="strict") as handle:
            return sum(1 for line in handle if line.strip())
    if kind in {"json_array_length", "json_pointer_integer", "json_pointer_length"}:
        payload = json.loads(path.read_text(encoding="utf-8"))
        value = payload if kind == "json_array_length" else _json_pointer(payload, str(spec.get("pointer", "")))
        if kind in {"json_array_length", "json_pointer_length"}:
            if not isinstance(value, (list, dict)):
                raise ValueError(f"{kind} target is not an array/object")
            return len(value)
        parsed = _integer(value)
        if parsed is None:
            raise ValueError("json_pointer_integer target is not a non-negative integer")
        return parsed
    if kind == "text_integer":
        text = path.read_text(encoding=spec.get("encoding", "utf-8")).strip()
        if not re.fullmatch(r"\d+", text):
            raise ValueError("text_integer file does not contain exactly one non-negative integer")
        return int(text)
    raise ValueError(
        "unsupported evidence kind; use delimited_rows, jsonl_rows, json_array_length, "
        "json_pointer_integer, json_pointer_length, text_integer, zip_member_rows or "
        "zip_member_lines"
    )


def _same_inventory(declared: object, actual: list[dict], label: str, problems: list[str]) -> None:
    if not isinstance(declared, list):
        problems.append(f"{label} must be an array generated by tools/data_manifest.py sync")
        return
    normalized = []
    for index, item in enumerate(declared):
        if not isinstance(item, dict):
            problems.append(f"{label}[{index}] is not an object")
            continue
        normalized.append({"path": item.get("path"), "sha256": item.get("sha256"), "bytes": item.get("bytes")})
    if normalized != actual:
        actual_paths = {x["path"] for x in actual}
        declared_paths = {str(x.get("path", "")) for x in normalized}
        missing = sorted(actual_paths - declared_paths)
        stale = sorted(declared_paths - actual_paths)
        detail = []
        if missing:
            detail.append("unregistered=" + ", ".join(missing[:4]))
        if stale:
            detail.append("missing/stale=" + ", ".join(stale[:4]))
        if not detail:
            detail.append("hash or byte count differs")
        problems.append(f"{label} does not match current files ({'; '.join(detail)})")


def _scan_caps(project: Path, files: list[dict], manifest: dict, state: object | None,
               problems: list[str]) -> None:
    pilot = manifest.get("pilot")
    pilot_ok = (
        isinstance(pilot, dict) and pilot.get("used") is True and
        pilot.get("excluded_from_analysis") is True and
        pilot.get("full_acquisition_completed_after_pilot") is True and
        manifest.get("status") == COMPLETE
    )
    sampling = manifest.get("protocol_sampling")
    sampling_decision = state.decision("protocol_sampling_authorized") if state is not None else None
    sampling_ok = (
        isinstance(sampling, dict) and sampling.get("pre_specified") is True and
        isinstance(sampling.get("protocol_path"), str) and
        len(str(sampling.get("explanation", "")).strip()) >= 40 and
        isinstance(sampling_decision, dict) and
        sampling_decision.get("value") == "YES" and
        len(str(sampling_decision.get("rationale", "")).strip()) >= 40
    )
    for item in files:
        path = project / str(item["path"])
        if path.suffix.lower() not in _TEXT_CODE_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", "//", "--")):
                continue
            for label, pattern in _CAP_PATTERNS:
                if not pattern.search(line):
                    continue
                if "MEDPAPER_PILOT_ONLY" in line and pilot_ok:
                    continue
                if "MEDPAPER_PROTOCOL_SAMPLING" in line and sampling_ok:
                    continue
                problems.append(
                    f"unapproved acquisition cap in {item['path']}:{line_no} ({label}); "
                    "remove it or use a validated pilot/protocol-sampling annotation"
                )


def validate(project: Path, state: object | None = None) -> Validation:
    problems: list[str] = []
    manifest_path = project / MANIFEST_REL
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Validation(False, [f"{MANIFEST_REL} missing"])
    except json.JSONDecodeError as exc:
        return Validation(False, [f"{MANIFEST_REL} is invalid JSON: {exc}"])
    if not isinstance(manifest, dict):
        return Validation(False, [f"{MANIFEST_REL} must contain one JSON object"])

    if manifest.get("schema_version") != SCHEMA_VERSION:
        problems.append(f"schema_version must be {SCHEMA_VERSION}")
    if manifest.get("requested_scope") != FULL_SCOPE:
        problems.append(f"requested_scope must be {FULL_SCOPE}; convenience subsets are not eligible")
    population = str(manifest.get("protocol_population", "")).strip()
    if len(population) < 20 or _PLACEHOLDER.search(population):
        problems.append("protocol_population must define the complete acquisition universe, not a placeholder")
    method = manifest.get("acquisition_method")
    if method not in _METHODS:
        problems.append(f"acquisition_method must be one of {sorted(_METHODS)}")

    raw_actual = raw_inventory(project)
    code_actual = inventory(project, "02_data/acquisition")
    if not raw_actual:
        problems.append("no acquired payload in 02_data/raw/ and no declared data source "
                        "(the user's own dataset: `wf data add <path>`, used in place)")
    if any(item["bytes"] == 0 for item in raw_actual):
        problems.append("raw inventory contains an empty file")
    if method == "scripted" and not code_actual:
        problems.append("scripted acquisition requires code under 02_data/acquisition/")
    _same_inventory(manifest.get("raw_files"), raw_actual, "raw_files", problems)
    _same_inventory(manifest.get("acquisition_files"), code_actual, "acquisition_files", problems)
    computed_bundle = bundle_sha256(raw_actual)
    if manifest.get("raw_bundle_sha256") != computed_bundle:
        problems.append("raw_bundle_sha256 does not match the current immutable raw inventory")

    raw_paths = {item["path"] for item in raw_actual}
    sources = manifest.get("sources")
    if not isinstance(sources, list) or not sources:
        problems.append("sources must contain at least one independently counted source")
        sources = []
    source_ids: set[str] = set()
    received_total = 0
    incomplete = 0
    source_counts: dict[str, int] = {}
    for index, source in enumerate(sources):
        label = f"sources[{index}]"
        if not isinstance(source, dict):
            problems.append(f"{label} is not an object")
            continue
        sid = str(source.get("id", "")).strip()
        if not sid or _PLACEHOLDER.search(sid) or sid in source_ids:
            problems.append(f"{label}.id is missing, placeholder, or duplicated")
        else:
            source_ids.add(sid)
        if source.get("type") not in _SOURCE_TYPES:
            problems.append(f"{label}.type must be one of {sorted(_SOURCE_TYPES)}")
        locator = str(source.get("locator", "")).strip()
        if len(locator) < 5 or _PLACEHOLDER.search(locator):
            problems.append(f"{label}.locator must identify the exact file, query, release, or endpoint")
        if not _aware_timestamp(source.get("retrieved_at")):
            problems.append(f"{label}.retrieved_at must be an ISO-8601 timestamp with timezone")
        expected = _integer(source.get("source_total_expected"))
        requested = _integer(source.get("records_requested"))
        received = _integer(source.get("records_received"))
        if expected is None or requested is None or received is None:
            problems.append(f"{label} count fields must be non-negative integers")
            continue
        try:
            proved_expected = evidence_count(project, source.get("source_total_evidence"), raw_paths)
            if proved_expected != expected:
                problems.append(f"{label}.source_total_expected={expected}, evidence proves {proved_expected}")
        except (OSError, UnicodeError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
            problems.append(f"{label}.source_total_evidence cannot be verified: {exc}")
        received_specs = source.get("received_count_evidence")
        if isinstance(received_specs, dict):
            received_specs = [received_specs]
        if not isinstance(received_specs, list) or not received_specs:
            problems.append(f"{label}.received_count_evidence must contain raw payload count proof")
        else:
            try:
                proved_received = sum(evidence_count(project, item, raw_paths) for item in received_specs)
                if proved_received != received:
                    problems.append(f"{label}.records_received={received}, evidence proves {proved_received}")
            except (OSError, UnicodeError, ValueError, KeyError, IndexError, json.JSONDecodeError) as exc:
                problems.append(f"{label}.received_count_evidence cannot be verified: {exc}")
        if source.get("truncation_applied") is not False:
            problems.append(f"{label}.truncation_applied must be false")
        complete = source.get("complete") is True
        if complete:
            if not (requested == received == expected):
                problems.append(
                    f"{label} claims complete but expected/requested/received are "
                    f"{expected}/{requested}/{received}"
                )
        else:
            incomplete += 1
            limit = source.get("source_limit")
            if not isinstance(limit, dict):
                problems.append(f"{label} is incomplete without a source_limit object")
            else:
                accessible = _integer(limit.get("accessible_total_expected"))
                reason = str(limit.get("reason", "")).strip()
                evidence = limit.get("evidence")
                evrel = evidence if isinstance(evidence, str) and evidence in raw_paths \
                    else _safe_rel(evidence, "02_data/raw")
                if accessible is None or requested != accessible or received != accessible:
                    problems.append(f"{label} must request and receive the entire source-accessible subset")
                if limit.get("source_imposed") is not True or len(reason) < 40:
                    problems.append(f"{label}.source_limit must document an external source-imposed restriction")
                if _CONVENIENCE_REASON.search(reason):
                    problems.append(f"{label}.source_limit is a convenience rationale, not an external restriction")
                if not evrel or evrel not in raw_paths:
                    problems.append(f"{label}.source_limit.evidence must be an inventoried raw receipt")
        pagination = source.get("pagination")
        if not isinstance(pagination, dict) or not isinstance(pagination.get("applicable"), bool):
            problems.append(f"{label}.pagination must explicitly state applicable true/false")
        elif pagination["applicable"]:
            pages_received = _integer(pagination.get("pages_received"))
            pages_expected = pagination.get("pages_expected")
            if pages_received is None or pages_received < 1:
                problems.append(f"{label}.pagination.pages_received must be positive")
            if pages_expected is not None:
                parsed_pages = _integer(pages_expected)
                if parsed_pages is None or parsed_pages != pages_received:
                    problems.append(f"{label} did not receive every expected page")
            if pagination.get("terminal_reached") is not True:
                problems.append(f"{label} pagination did not reach the terminal page/cursor")
            terminal_cursor = pagination.get("next_cursor_at_end")
            if not (terminal_cursor is None or terminal_cursor == "" or terminal_cursor is False):
                problems.append(f"{label} still has a next cursor after the claimed final page")
        received_total += received
        source_counts[sid] = received

    status = manifest.get("status")
    if status == COMPLETE:
        if incomplete:
            problems.append("status=complete but one or more sources are incomplete")
    elif status == LIMITED:
        if not incomplete:
            problems.append("source_limited_user_authorized requires at least one incomplete source")
        decision = state.decision("partial_data_authorized") if state is not None else None
        if not decision or decision.get("value") != "YES" or len(str(decision.get("rationale", "")).strip()) < 40:
            problems.append(
                "source-limited acquisition requires the user's explicit partial_data_authorized=YES decision"
            )
    else:
        problems.append(f"status must be {COMPLETE} or {LIMITED}")

    protocol_sampling = manifest.get("protocol_sampling")
    if protocol_sampling is not None:
        sampling_decision = state.decision("protocol_sampling_authorized") if state is not None else None
        if not isinstance(protocol_sampling, dict) or protocol_sampling.get("pre_specified") is not True:
            problems.append("protocol_sampling must be null or a pre-specified sampling-design object")
        if (not sampling_decision or sampling_decision.get("value") != "YES" or
                len(str(sampling_decision.get("rationale", "")).strip()) < 40):
            problems.append(
                "a sampled acquisition universe requires the user's explicit "
                "protocol_sampling_authorized=YES decision"
            )

    try:
        summary = json.loads((project / SUMMARY_REL).read_text(encoding="utf-8"))
    except FileNotFoundError:
        summary = None
        problems.append(f"{SUMMARY_REL} missing")
    except json.JSONDecodeError as exc:
        summary = None
        problems.append(f"{SUMMARY_REL} is invalid JSON: {exc}")
    analysis = manifest.get("analysis_dataset")
    if not isinstance(analysis, dict):
        problems.append("analysis_dataset reconciliation object is missing")
    elif isinstance(summary, dict):
        n_rows = _integer(summary.get("n_rows"))
        declared_rows = _integer(analysis.get("n_rows"))
        if n_rows is None or declared_rows != n_rows:
            problems.append("analysis_dataset.n_rows must equal dataset_summary.json n_rows")
        if summary.get("source_hash") != computed_bundle:
            problems.append("dataset_summary.json source_hash must equal raw_bundle_sha256")
        if summary.get("acquisition_scope") != FULL_SCOPE:
            problems.append(f"dataset_summary.json acquisition_scope must be {FULL_SCOPE}")
        if summary.get("acquisition_status") != status:
            problems.append("dataset_summary.json acquisition_status must equal the manifest status")
        primary = str(analysis.get("primary_source_id", "")).strip()
        if primary not in source_counts:
            problems.append("analysis_dataset.primary_source_id does not name a source")
        relationship = analysis.get("relationship")
        excluded = _integer(analysis.get("excluded_after_acquisition"))
        if relationship == "one_record_per_analysis_row":
            if excluded is None or n_rows is None or source_counts.get(primary) != n_rows + excluded:
                problems.append("primary received records must equal analysis rows plus post-acquisition exclusions")
        elif relationship == "complex_join":
            if len(str(analysis.get("explanation", "")).strip()) < 40:
                problems.append("complex_join requires a substantive count-reconciliation explanation")
        else:
            problems.append("analysis_dataset.relationship must be one_record_per_analysis_row or complex_join")

    _scan_caps(project, code_actual, manifest, state, problems)
    return Validation(
        not problems, problems, sources=len(sources), records_received=received_total,
        raw_files=len(raw_actual), bundle_sha256=computed_bundle,
    )
