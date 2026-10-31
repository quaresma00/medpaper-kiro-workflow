"""1.14.1 (B6): numbers in text that are not scientific facts (stdlib only).

Software and package versions ("Python 3.13.12", "R 4.5.2", "pandas 3.0.5", "version 2.1"),
URLs, DOIs and accession/approval/registration identifiers carry digits but report no
result. Number provenance used to extract them: "3.0" of pandas 3.0.5 passed only because it
coincided with a result value, and "0003" in a regulator URL was traced to a model estimate.
`strip(text)` blanks them before numbers are extracted, so they are neither required to come
from the results JSON nor matched to it by coincidence. Environment versions may therefore
appear in Methods. The patterns only fire in identifier contexts (a software name, the word
"version", a URL/DOI, a registry prefix, "approval no." ...), never on a bare statistic.
"""
from __future__ import annotations

import re

# Software whose name is followed by a two-part version ("Stata 18.0", "SAS 9.4"). Names that
# are also clinical words (survival, meta, mice, R, Stan) are left out; any version with three
# or more parts ("R 4.5.2", "survival 3.5.7") is caught by DOTTED_RE whatever the name.
SOFTWARE = (
    r"Python|RStudio|SAS|Stata|SPSS|IBM\s+SPSS(?:\s+Statistics)?|MedCalc|GraphPad\s+Prism|"
    r"GraphPad|JMP|Microsoft\s+Excel|MATLAB|Julia|PostgreSQL|SQLite|MySQL|pandas|numpy|NumPy|"
    r"scipy|SciPy|statsmodels|scikit-learn|lifelines|matplotlib|seaborn|pyarrow|polars|"
    r"openpyxl|python-docx|pypdf|PyMuPDF|Pandoc|pandoc|LibreOffice|ggplot2|survminer|tidyverse|"
    r"dplyr|data\.table|lme4|metafor|MatchIt|WeightIt|cobalt|tableone|gtsummary|glmnet|brms|"
    r"rstan|knitr|rmarkdown|OpenVigil|MedDRA")

URL_RE = re.compile(r"\b(?:https?://|ftp://|www\.)[^\s<>\"')\]]+", re.I)
DOI_RE = re.compile(r"\b(?:doi:\s*|https?://(?:dx\.)?doi\.org/)?10\.\d{4,9}/[^\s<>\"')\]]+", re.I)
# Any dotted number with three or more parts is a version or an identifier, never a statistic.
DOTTED_RE = re.compile(r"(?<![\w.])v?\d+(?:\.\d+){2,}(?:[-+][A-Za-z0-9]+)*(?![\w.])")
VERSION_WORD_RE = re.compile(r"\bversion\s+\d+(?:\.\d+)*[a-z]?\b|\bv\d+(?:\.\d+)+\b", re.I)
SOFTWARE_RE = re.compile(
    rf"\b(?:{SOFTWARE})\b(?:\s+(?:package|software|language|statistical\s+software))?"
    r"\s*\(?\s*(?:version\s+|v\.?\s*)?\d+(?:\.\d+)+[a-z]?\b")
# Identifiers: approvals, registrations, accessions, grants. The keyword is followed (within a
# few words) by "no./number/ID/code/#" and ONE identifier token that holds a digit.
ID_WORDS = (r"approval|approved|IRB|ethics(?:\s+committee)?|registration|registered|registry|"
            r"reference|protocol|accession|license|licence|grant|award|permit|application")
ID_RE = re.compile(
    rf"\b(?:{ID_WORDS})\b[^.\n;:]{{0,25}}?(?:\b(?:nos?|number|ID|code)\b\.?|#)\s*[:#]?\s*"
    r"[A-Za-z0-9][\w./-]*\d[\w./-]*", re.I)
REGISTRY_RE = re.compile(r"\b(?:NCT\d{8}|CRD\d{8,}|ChiCTR[-\w]*\d+|ISRCTN\d+|DRKS\d+|"
                         r"EUCTR[\d-]+\w*|jRCT\w*\d+|UMIN\d+|ACTRN\d+|KCT\d+|CTRI/[\d/]+|"
                         r"PRJ[NED][A-Z]?\d+|GSE\d+|SRP\d+|E-MTAB-\d+)\b")


def strip(text: str) -> str:
    """The text with versions, URLs, DOIs and identifiers blanked."""
    text = URL_RE.sub(" ", text)
    text = DOI_RE.sub(" ", text)
    text = REGISTRY_RE.sub(" ", text)
    text = ID_RE.sub(" ", text)
    text = SOFTWARE_RE.sub(" ", text)
    text = DOTTED_RE.sub(" ", text)
    return VERSION_WORD_RE.sub(" ", text)
