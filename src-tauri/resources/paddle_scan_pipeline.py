#!/usr/bin/env python3
\
\
\
\
\
\


from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import statistics
import sys
import tempfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pymupdf

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LONE_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")
DISALLOWED_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PURE_PAGE_NUMBER_RE = re.compile(
    r"^(?:[-—–·•\s]*)(?:\d{1,4}|[ivxlcdm]{1,8}|第?\s*\d{1,4}\s*页)(?:[-—–·•\s]*)$",
    re.IGNORECASE,
)
DOT_LEADER_RE = re.compile(r"[.．·•…—_]{2,}")
TRAILING_PAGE_RE = re.compile(r"^(?P<title>.*?)(?:\s|[.．·•…—_])+(?P<page>\d{1,4})$")
DIAGRAM_TOKEN_PATTERN = r"[([{]?[xyzabc][0-9il]{0,3}[)\]}]?"
DIAGRAM_LABEL_RE = re.compile(
    rf"^(?:{DIAGRAM_TOKEN_PATTERN}|{DIAGRAM_TOKEN_PATTERN}\s*[=<>]\s*[0-9il]+|[{{}}\[\]()|\\/]+)$",
    re.IGNORECASE,
)
DIAGRAM_SEQUENCE_RE = re.compile(
    rf"^(?:{DIAGRAM_TOKEN_PATTERN}(?:\s+|[,，;；、(){{}}\[\]=<>/\\])+){1,}{DIAGRAM_TOKEN_PATTERN}$",
    re.IGNORECASE,
)
FOOTNOTE_MARKER_RE = re.compile(
    r"^\s*(?:[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚]|\[\d{1,2}\]|\(\d{1,2}\)|\d{1,2}[）).、])"
)
INLINE_CIRCLED_NOTE_RE = re.compile(r"[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳㉑㉒㉓㉔㉕㉖㉗㉘㉙㉚]")
INLINE_BRACKET_NOTE_RE = re.compile(
    r"(?<=[\u3400-\u9fff》〉】〕］）”’])(?:\s*)(?:\[\d{1,3}\]|［\d{1,3}］|\(\d{1,3}\)|（\d{1,3}）|(?:注|註)\s*\d{1,3})(?=(?:[，。！？；：、,.!?;:]|\s|$))"
)
INLINE_SYMBOL_NOTE_RE = re.compile(
    r"(?<=[\u3400-\u9fff》〉】〕］）”’])(?:\s*)[*＊†‡]+(?=(?:[，。！？；：、,.!?;:]|\s|$))"
)
RUNNING_HEADER_WITH_PAGE_RE = re.compile(
    r"^(?:\d{1,4}\s*[^\d\W].{1,36}|.{1,36}[^\d\W]\s*\d{1,4})$",
    re.UNICODE,
)
CITATION_LINE_RE = re.compile(
    r"^《[^》]{1,60}》(?:[①②③④⑤⑥⑦⑧⑨⑩])?(?:[，,]\s*(?:[IVXLCDM]+|第.+))?$",
    re.IGNORECASE,
)
CREDIT_LINE_RE = re.compile(
    r"^(?=.{2,32}$)(?:[^，。！？；：]{1,22})(?:著|译|编|校|绘|注|选编|主编)(?:\s*[^，。！？；：]{1,18}(?:译|校|编))?$"
)
STRONG_SENTENCE_END = "。！？!?；;：:…"
PAGE_FINAL_SENTENCE_END = "。！？!?"
REVIEW_SCORE_THRESHOLD = 0.78
TRAILING_CLOSERS = "”’）》〉】〕］｝)]}"
DIALOGUE_OPENERS = "“‘\"\'"
DIALOGUE_CLOSERS = "”’\"\'"
HEADING_MARKER = "\ue000"
OPEN_PUNCTUATION = "“‘（《〈【〔［｛(<\"'"
CLOSE_PUNCTUATION = "，。！？；：、）】》〉〕］｝…—,.!?;:)]}>%％℃°\"'"
SENTENCE_END = "。！？!?；;：:…"
PAGE_FINAL_SENTENCE_END = "。！？!?"
REVIEW_SCORE_THRESHOLD = 0.78


@dataclass
class OcrLine:
    text: str
    score: float
    box: tuple[float, float, float, float]
    source_index: int
    dropped_reason: str | None = None
    unicode_sanitized: bool = False

    @property
    def x0(self) -> float:
        return self.box[0]

    @property
    def y0(self) -> float:
        return self.box[1]

    @property
    def x1(self) -> float:
        return self.box[2]

    @property
    def y1(self) -> float:
        return self.box[3]

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def center_y(self) -> float:
        return (self.y0 + self.y1) / 2.0


@dataclass
class PageResult:
    page_number: int
    image_width: int
    image_height: int
    page_type: str
    average_confidence: float
    raw_lines: list[OcrLine]
    kept_lines: list[OcrLine]
    paragraphs: list[str]
    speech_chunks: list[str]
    text: str
    warnings: list[str]


@dataclass
class PipelineConfig:
    dpi: int
    language: str
    model_tier: str
    score_threshold: float
    filter_margins: bool
    drop_diagram_labels: bool
    drop_footnotes: bool
    skip_toc: bool
    drop_running_headers: bool
    drop_citation_lines: bool
    drop_credit_lines: bool
    use_orientation: bool
    font_name: str
    font_size: float
    min_chunk_chars: int
    max_chunk_chars: int
    merge_continuous_pages: bool
    review_score_threshold: float
    reading_profile: str
    content_start_mode: str
    content_start_page: int | None
    keep_title_page: bool


def sanitize_unicode_text(value: Any) -> tuple[str, int]:
\
\
\
\
\
\

    text = str(value)
    text, surrogate_count = LONE_SURROGATE_RE.subn("", text)
    text, control_count = DISALLOWED_CONTROL_RE.subn("", text)
    return text, surrogate_count + control_count


def safe_text(value: Any) -> str:
    return sanitize_unicode_text(value)[0]


def sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return safe_text(value)
    if isinstance(value, list):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {safe_text(key): sanitize_json_value(item) for key, item in value.items()}
    return value


def log(message: str) -> None:
    print(safe_text(message), flush=True)


def normalize_inline(text: str) -> str:
    text = safe_text(text)
    text = (
        text.replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\u00ad", "")
    )
    text = re.sub(r"[ \t]+", " ", text).strip()
    text = re.sub(r"(?<=[\u3400-\u9fff]) +(?=[\u3400-\u9fff])", "", text)
    text = re.sub(r"(?<=[\u3400-\u9fff]) +(?=[，。！？；：、）】》〉〕］｝…])", "", text)
    text = re.sub(r"(?<=[（【《〈〔［｛“‘]) +(?=[\u3400-\u9fff])", "", text)
    text = re.sub(r"\s+([，。！？；：、）】》〉〕］｝…,.!?;:])", r"\1", text)
    text = re.sub(r"([（【《〈〔［｛“‘])\s+", r"\1", text)
    text = re.sub(r"(?<=[A-Za-z]),(?=[A-Za-z])", ", ", text)
    text = re.sub(r"(?<=\d)[一—–](?=\d)", "-", text)
    return text.strip()


def remove_inline_note_markers(text: str) -> str:

    text = INLINE_CIRCLED_NOTE_RE.sub("", text)
    text = INLINE_BRACKET_NOTE_RE.sub("", text)
    text = INLINE_SYMBOL_NOTE_RE.sub("", text)
    return normalize_inline(text)


def normalize_reading_punctuation(text: str) -> str:

    text = text.replace("［", "【").replace("］", "】")


    chars = list(text)
    stack: list[int] = []
    pairs: list[tuple[int, int]] = []
    for index, char in enumerate(chars):
        if char == "(":
            stack.append(index)
        elif char == ")" and stack:
            pairs.append((stack.pop(), index))
    for start, end in pairs:
        content = "".join(chars[start + 1 : end])
        if CJK_RE.search(content) and not re.fullmatch(r"[A-Za-z0-9_+\-*/=,.\s]+", content):
            chars[start] = "（"
            chars[end] = "）"
    text = "".join(chars)


    chars = list(text)
    inner_depth = 0
    outer_depth = 0
    for index, char in enumerate(chars):
        if char == "《":
            outer_depth += 1
        elif char == "》":
            outer_depth = max(0, outer_depth - 1)
        elif char in {"〈", "<"} and outer_depth > 0:
            chars[index] = "〈"
            inner_depth += 1
        elif char in {"〉", ">"} and inner_depth > 0:
            chars[index] = "〉"
            inner_depth -= 1
    text = "".join(chars)


    text = re.sub(r'"([^"\n]*[\u3400-\u9fff][^"\n]*)"', r'“\1”', text)
    text = re.sub(r"'([^'\n]*[\u3400-\u9fff][^'\n]*)'", r"‘\1’", text)


    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[；;]{2,}", "；", text)
    text = re.sub(r"[：:]{2,}", "：", text)
    text = re.sub(r"、{2,}", "、", text)
    text = re.sub(r"(?<=[\u3400-\u9fff》〉】〕］”’])\)(?=(?:[，。！？；：、\s]|$))", "）", text)
    return normalize_inline(text)


def clean_reading_text(text: str, drop_inline_notes: bool) -> str:
    heading = text.startswith(HEADING_MARKER)
    cleaned = strip_heading_marker(text)
    if drop_inline_notes:
        cleaned = remove_inline_note_markers(cleaned)
    cleaned = normalize_reading_punctuation(cleaned)
    return (HEADING_MARKER if heading else "") + cleaned if cleaned else ""


def smart_join(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if not left:
        return right
    if not right:
        return left
    last, first = left[-1], right[0]
    if last == "-" and first.isalpha():
        return left[:-1] + right
    if CJK_RE.search(last) or CJK_RE.search(first):
        return left + right
    if last in OPEN_PUNCTUATION or first in CLOSE_PUNCTUATION:
        return left + right
    if last.isalnum() and first.isalnum():
        return left + " " + right
    return left + right


def stable_signature(text: str) -> str:
    text = normalize_inline(text).lower()
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"\s+", "", text)
    return text


def find_result_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        if "rec_texts" in value and ("rec_boxes" in value or "rec_polys" in value):
            return value
        for nested in value.values():
            try:
                return find_result_mapping(nested)
            except LookupError:
                pass
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            try:
                return find_result_mapping(nested)
            except LookupError:
                pass
    raise LookupError("PaddleOCR result does not contain rec_texts/rec_boxes")


def to_plain_json(result: Any) -> Mapping[str, Any]:
    payload = getattr(result, "json", None)
    if callable(payload):
        payload = payload()
    if payload is None:
        payload = result
    if isinstance(payload, str):
        payload = json.loads(payload)
    return find_result_mapping(payload)


def as_box(raw_box: Sequence[Any]) -> tuple[float, float, float, float]:
    if len(raw_box) == 4 and all(isinstance(value, (int, float)) for value in raw_box):
        x0, y0, x1, y1 = (float(value) for value in raw_box)
        return x0, y0, x1, y1
    points = [point for point in raw_box if isinstance(point, Sequence) and len(point) >= 2]
    if not points:
        raise ValueError("invalid OCR box")
    xs = [float(point[0]) for point in points]
    ys = [float(point[1]) for point in points]
    return min(xs), min(ys), max(xs), max(ys)


def extract_lines(result: Any, score_threshold: float) -> list[OcrLine]:
    mapping = to_plain_json(result)
    texts = list(mapping.get("rec_texts", []))
    scores = list(mapping.get("rec_scores", []))
    boxes = list(mapping.get("rec_boxes", [])) or list(mapping.get("rec_polys", []))
    lines: list[OcrLine] = []
    for index, text in enumerate(texts):
        raw_text, sanitized_count = sanitize_unicode_text(text)
        cleaned = normalize_inline(raw_text)
        if not cleaned or index >= len(boxes):
            continue
        score = float(scores[index]) if index < len(scores) else 0.0
        try:
            box = as_box(boxes[index])
        except (TypeError, ValueError):
            continue
        line = OcrLine(cleaned, score, box, index, unicode_sanitized=sanitized_count > 0)
        if score < score_threshold:
            line.dropped_reason = f"low_confidence:{score:.3f}"
        lines.append(line)
    return lines


def cluster_rows(lines: Sequence[OcrLine]) -> list[list[OcrLine]]:
    if not lines:
        return []
    ordered = sorted(lines, key=lambda line: (line.center_y, line.x0))
    rows: list[list[OcrLine]] = []
    for line in ordered:
        best_row: list[OcrLine] | None = None
        best_distance = math.inf
        for row in rows[-4:]:
            median_y = statistics.median(item.center_y for item in row)
            median_height = statistics.median(max(1.0, item.height) for item in row)
            distance = abs(line.center_y - median_y)
            if distance <= max(median_height, line.height) * 0.62 and distance < best_distance:
                best_row = row
                best_distance = distance
        if best_row is None:
            rows.append([line])
        else:
            best_row.append(line)
    for row in rows:
        row.sort(key=lambda line: line.x0)
    rows.sort(key=lambda row: statistics.median(line.center_y for line in row))
    return rows


def row_text(row: Sequence[OcrLine], page_width: float, toc: bool = False) -> str:
    if not row:
        return ""
    ordered = sorted(row, key=lambda line: line.x0)
    if toc and len(ordered) >= 2:
        trailing = ordered[-1]
        title_parts = ordered[:-1]
        if PURE_PAGE_NUMBER_RE.fullmatch(trailing.text) and trailing.x0 > page_width * 0.5:
            title = ""
            for part in title_parts:
                title = smart_join(title, part.text)
            return f"{normalize_inline(title)} …… {trailing.text.strip()}"
    merged = ""
    previous: OcrLine | None = None
    for item in ordered:
        if merged and previous is not None:
            gap = item.x0 - previous.x1
            if gap > max(item.height * 2.2, page_width * 0.035) and not CJK_RE.search(merged[-1:]):
                merged += " "
        merged = smart_join(merged, item.text)
        previous = item
    return normalize_inline(merged)



def is_dialogue_text(text: str) -> bool:
    compact = normalize_inline(strip_heading_marker(text))
    if not compact:
        return False
    if compact[0] in DIALOGUE_OPENERS:
        return True

    return len(compact) <= 24 and compact.endswith(tuple("！？!?。")) and any(
        marker in compact for marker in ("吗", "呢", "吧", "啊", "呀", "哦", "哎")
    )


def has_unclosed_dialogue_quote(text: str) -> bool:

    compact = normalize_inline(strip_heading_marker(text))
    if not compact:
        return False
    curly_open = compact.count("“") - compact.count("”")
    single_open = compact.count("‘") - compact.count("’")
    straight_double = compact.count('"') % 2
    straight_single = compact.count("'") % 2
    return curly_open > 0 or single_open > 0 or bool(straight_double or straight_single)


def merge_vertical_title_rows(rows: Sequence[Sequence[OcrLine]], page_width: float) -> list[str]:

    normal: list[str] = []
    stack: list[tuple[str, float, float]] = []

    def flush_stack() -> None:
        nonlocal stack
        if not stack:
            return
        if len(stack) >= 2:
            centers = [center for _text, center, _height in stack]
            spread = max(centers) - min(centers)
            median_height = statistics.median(height for _text, _center, height in stack)
            if spread <= max(page_width * 0.08, median_height * 1.8):
                normal.append("".join(text for text, _center, _height in stack))
            else:
                normal.extend(text for text, _center, _height in stack)
        else:
            normal.append(stack[0][0])
        stack = []

    for row in rows:
        text = row_text(row, page_width)
        if not text:
            continue
        x0 = min(line.x0 for line in row)
        x1 = max(line.x1 for line in row)
        height = max(line.y1 for line in row) - min(line.y0 for line in row)
        center = (x0 + x1) / 2.0
        compact = normalize_inline(text)
        vertical_glyph = len(compact) <= 2 and bool(CJK_RE.fullmatch(compact))
        if vertical_glyph:
            if stack and abs(center - statistics.median(item[1] for item in stack)) > max(page_width * 0.08, height * 1.8):
                flush_stack()
            stack.append((compact, center, max(1.0, height)))
        else:
            flush_stack()
            normal.append(compact)
    flush_stack()
    if any(CJK_RE.search(item) for item in normal):
        normal = [
            item
            for item in normal
            if CJK_RE.search(item) or len(item) > 3 or re.search(r"[A-Za-z]{2,}", item)
        ]
    return normal


def refine_sparse_title_page(page: PageResult) -> None:

    active = [line for line in page.kept_lines if line.dropped_reason is None]
    if not active or len(active) > 8:
        return
    cjk_lines = [line for line in active if CJK_RE.search(normalize_inline(line.text))]
    if not cjk_lines:
        return
    total_chars = sum(len(normalize_inline(line.text)) for line in active)
    if total_chars > 60:
        return
    for line in active:
        compact = normalize_inline(line.text)
        if PURE_PAGE_NUMBER_RE.fullmatch(compact) or re.fullmatch(r"[?？!！•·●○◎◉◌0-9Il|\-—_]{1,5}", compact):
            line.dropped_reason = "title_artifact"
    remaining = [line for line in active if line.dropped_reason is None]
    if remaining and any(CJK_RE.search(line.text) for line in remaining):
        page.kept_lines = remaining
        page.page_type = "title"
        page.warnings.append("sparse_title_refined")


def resolve_reading_profile(paragraphs: Sequence[str], requested: str) -> str:
    if requested in {"prose", "novel"}:
        return requested
    useful = [strip_heading_marker(item) for item in paragraphs if strip_heading_marker(item)]
    dialogue_count = sum(1 for item in useful if is_dialogue_text(item))
    if dialogue_count >= 3 or (useful and dialogue_count / len(useful) >= 0.18):
        return "novel"
    return "prose"

def detect_page_type(lines: Sequence[OcrLine], width: float, height: float) -> str:
    usable = [line for line in lines if line.dropped_reason is None]
    if not usable or sum(len(line.text) for line in usable) < 2:
        return "blank"
    rows = cluster_rows(usable)
    texts = [row_text(row, width) for row in rows]
    joined = "".join(texts)
    if "目录" in joined[:80]:
        return "toc"
    trailing_numeric = sum(
        1
        for text in texts
        if TRAILING_PAGE_RE.match(text) or (text and PURE_PAGE_NUMBER_RE.fullmatch(text.split()[-1] if text.split() else ""))
    )
    short_rows = sum(1 for text in texts if 1 <= len(text) <= 35)
    if len(rows) >= 5 and trailing_numeric >= 3 and short_rows >= len(rows) * 0.55:
        return "toc"
    median_height = statistics.median(max(1.0, line.height) for line in usable)
    density = sum(line.width * line.height for line in usable) / max(1.0, width * height)
    if len(rows) <= 8 and median_height > height * 0.025 and density < 0.08:
        return "title"
    tiny = sum(1 for line in usable if len(line.text) <= 4 and line.width < width * 0.15)
    if tiny >= 5 and sum(len(line.text) for line in usable) < 220:
        return "diagram"
    return "body"


def is_margin_line(line: OcrLine, page_height: float) -> bool:
    return line.y1 < page_height * 0.12 or line.y0 > page_height * 0.86


def median_body_height(lines: Sequence[OcrLine], page_height: float) -> float:
    central = [
        max(1.0, line.height)
        for line in lines
        if line.dropped_reason is None
        and line.y0 > page_height * 0.12
        and line.y1 < page_height * 0.82
        and len(line.text) >= 2
    ]
    if not central:
        central = [max(1.0, line.height) for line in lines if line.dropped_reason is None]
    return statistics.median(central) if central else max(1.0, page_height * 0.02)


def footnote_cutoff_y(lines: Sequence[OcrLine], page_height: float) -> float | None:
    body_height = median_body_height(lines, page_height)
    candidates = [
        line.y0
        for line in lines
        if line.dropped_reason is None
        and line.y0 > page_height * 0.52
        and FOOTNOTE_MARKER_RE.match(normalize_inline(line.text))
        and line.height <= body_height * 1.18
    ]
    return min(candidates) if candidates else None


def is_running_header_with_page(text: str) -> bool:
    compact = normalize_inline(text)
    return len(compact) <= 42 and bool(RUNNING_HEADER_WITH_PAGE_RE.fullmatch(compact))


def is_citation_line(line: OcrLine, page_width: float, page_height: float) -> bool:
    text = normalize_inline(line.text)
    if not CITATION_LINE_RE.fullmatch(text):
        return False
    centered = line.x0 > page_width * 0.12 and line.x1 < page_width * 0.88
    near_title_area = line.y0 < page_height * 0.48
    return centered and near_title_area and line.width < page_width * 0.75


def is_credit_line(line: OcrLine, page_width: float, page_height: float) -> bool:
    text = normalize_inline(line.text)
    if not CREDIT_LINE_RE.fullmatch(text):
        return False



    centered = line.x0 > page_width * 0.10 and line.x1 < page_width * 0.90
    narrow = line.width < page_width * 0.58
    not_top_running_header = line.y0 > page_height * 0.08
    return centered and narrow and not_top_running_header


def is_diagram_only_text(text: str) -> bool:
    compact = normalize_inline(text)
    if CJK_RE.search(compact):
        return False
    if DIAGRAM_LABEL_RE.fullmatch(compact) or DIAGRAM_SEQUENCE_RE.fullmatch(compact):
        return True
    tokens = re.findall(DIAGRAM_TOKEN_PATTERN, compact, flags=re.IGNORECASE)
    other = re.sub(
        rf"{DIAGRAM_TOKEN_PATTERN}|[\s,，;；、(){{}}\[\]=<>/\\]",
        "",
        compact,
        flags=re.IGNORECASE,
    )
    return len(tokens) >= 2 and not other


def collect_repeated_margins(pages: Sequence[PageResult]) -> set[str]:
    counts: Counter[str] = Counter()
    page_count = max(1, len(pages))
    for page in pages:
        seen: set[str] = set()
        for line in page.raw_lines:
            if line.dropped_reason is None and is_margin_line(line, page.image_height):
                signature = stable_signature(line.text)
                if len(signature) >= 2:
                    seen.add(signature)
        counts.update(seen)
    threshold = max(2, math.ceil(page_count * 0.08))
    return {signature for signature, count in counts.items() if count >= threshold}


def filter_page_lines(
    page: PageResult,
    repeated_margins: set[str],
    config: PipelineConfig,
) -> list[OcrLine]:
    kept: list[OcrLine] = []
    note_cutoff = footnote_cutoff_y(page.raw_lines, page.image_height) if config.drop_footnotes else None
    body_height = median_body_height(page.raw_lines, page.image_height)
    for line in page.raw_lines:
        if line.dropped_reason is not None:
            continue
        text = normalize_inline(line.text)
        if not text:
            line.dropped_reason = "empty"
            continue

        in_top = line.y1 < page.image_height * 0.12
        in_bottom = line.y0 > page.image_height * 0.86

        if note_cutoff is not None and line.y0 >= note_cutoff - body_height * 0.15:
            line.dropped_reason = "footnote"
            continue

        if config.filter_margins and (in_top or in_bottom):
            toc_entry_number = (
                page.page_type == "toc"
                and PURE_PAGE_NUMBER_RE.fullmatch(text)
                and line.x0 > page.image_width * 0.50
                and line.y0 < page.image_height * 0.86
            )
            if PURE_PAGE_NUMBER_RE.fullmatch(text) and not toc_entry_number:
                line.dropped_reason = "page_number"
                continue
            if config.drop_running_headers and is_running_header_with_page(text):
                line.dropped_reason = "running_header"
                continue
            if config.drop_running_headers and stable_signature(text) in repeated_margins:
                line.dropped_reason = "repeated_margin"
                continue

        if config.drop_citation_lines and is_citation_line(
            line, page.image_width, page.image_height
        ):
            line.dropped_reason = "citation_attribution"
            continue

        if config.drop_credit_lines and is_credit_line(
            line, page.image_width, page.image_height
        ):
            line.dropped_reason = "author_or_translator_credit"
            continue

        if config.drop_diagram_labels and is_diagram_only_text(text):
            short_or_narrow = (
                line.width < page.image_width * 0.72
                or line.height < page.image_height * 0.055
            )
            if page.page_type == "diagram" or short_or_narrow:
                line.dropped_reason = "diagram_label"
                continue

        kept.append(line)
    return kept


def estimate_columns(lines: Sequence[OcrLine], width: float) -> list[list[OcrLine]]:
    body = [line for line in lines if line.width < width * 0.78]
    left = [line for line in body if line.x1 < width * 0.56]
    right = [line for line in body if line.x0 > width * 0.44]
    if len(left) >= 5 and len(right) >= 5:
        overlap_rows = 0
        for left_line in left:
            if any(abs(left_line.center_y - right_line.center_y) < max(left_line.height, right_line.height) for right_line in right):
                overlap_rows += 1
        if overlap_rows >= min(len(left), len(right)) * 0.35:
            full_width = [line for line in lines if line not in left and line not in right]
            top_full = [line for line in full_width if line.y1 < min(item.y0 for item in left + right)]
            bottom_full = [line for line in full_width if line.y0 > max(item.y1 for item in left + right)]
            columns = []
            if top_full:
                columns.append(sorted(top_full, key=lambda line: (line.y0, line.x0)))
            columns.append(sorted(left, key=lambda line: (line.y0, line.x0)))
            columns.append(sorted(right, key=lambda line: (line.y0, line.x0)))
            if bottom_full:
                columns.append(sorted(bottom_full, key=lambda line: (line.y0, line.x0)))
            return columns
    return [sorted(lines, key=lambda line: (line.y0, line.x0))]


def lines_to_paragraphs(lines: Sequence[OcrLine], width: float, page_type: str) -> list[str]:
    if not lines:
        return []
    rows = cluster_rows(lines)
    if page_type == "toc":
        return [text for row in rows if (text := row_text(row, width, toc=True))]
    if page_type == "title":
        return [HEADING_MARKER + text for text in merge_vertical_title_rows(rows, width) if text]
    if page_type == "diagram":
        return [text for row in rows if (text := row_text(row, width))]

    paragraphs: list[str] = []
    for column in estimate_columns(lines, width):
        flattened: list[tuple[str, float, float, float, float]] = []
        for row in cluster_rows(column):
            text = row_text(row, width)
            if not text:
                continue
            x0 = min(line.x0 for line in row)
            x1 = max(line.x1 for line in row)
            y0 = min(line.y0 for line in row)
            y1 = max(line.y1 for line in row)
            flattened.append((text, x0, x1, y0, y1))

        if not flattened:
            continue

        heights = [max(1.0, y1 - y0) for _, _, _, y0, y1 in flattened]
        median_height = statistics.median(heights)
        positive_gaps = [
            current[3] - previous[4]
            for previous, current in zip(flattened, flattened[1:])
            if 0 <= current[3] - previous[4] <= median_height * 3.5
        ]
        normal_gap = statistics.median(positive_gaps) if positive_gaps else median_height * 0.45
        char_widths = [
            (x1 - x0) / max(1, len(text))
            for text, x0, x1, _y0, _y1 in flattened
            if len(text) >= 2 and x1 > x0
        ]
        median_char_width = statistics.median(char_widths) if char_widths else median_height * 0.75
        left_positions = sorted(x0 for _, x0, _, _, _ in flattened)
        lower_count = max(1, math.ceil(len(left_positions) * 0.35))
        base_left = statistics.median(left_positions[:lower_count])

        current_text = ""
        current_is_heading = False
        previous: tuple[str, float, float, float, float] | None = None
        previous_was_heading = False
        for item in flattened:
            text, x0, x1, y0, y1 = item
            line_width = x1 - x0
            centered_short = (
                len(text) <= 38
                and x0 > width * 0.14
                and x1 < width * 0.86
                and line_width < width * 0.68
            )
            start_new = previous_was_heading
            current_starts_dialogue = is_dialogue_text(text)
            if previous is not None:
                prev_text, _prev_x0, _prev_x1, _prev_y0, prev_y1 = previous
                gap = y0 - prev_y1
                large_gap = gap > max(normal_gap * 2.0, median_height * 0.95)
                indented = x0 - base_left > max(median_char_width * 1.35, median_height * 0.70)
                if large_gap:
                    start_new = True
                elif indented and prev_text.endswith(tuple(SENTENCE_END)):
                    start_new = True


                if current_starts_dialogue and (is_dialogue_text(prev_text) or prev_text.endswith(tuple(SENTENCE_END))):
                    start_new = True
                if centered_short and (len(text) <= 20 or gap > normal_gap * 1.20):
                    start_new = True

            if start_new and current_text:
                cleaned = normalize_inline(current_text)
                if cleaned:
                    paragraphs.append((HEADING_MARKER if current_is_heading else "") + cleaned)
                current_text = text
                current_is_heading = centered_short and len(text) <= 38 and not any(mark in text for mark in "，。！？；：,!?;:")
            else:
                if not current_text:
                    current_is_heading = centered_short and len(text) <= 38 and not any(mark in text for mark in "，。！？；：,!?;:")
                current_text = smart_join(current_text, text)

            previous = item
            previous_was_heading = centered_short and len(text) <= 38 and not any(mark in text for mark in "，。！？；：,!?;:")

        if current_text:
            cleaned = normalize_inline(current_text)
            if cleaned:
                paragraphs.append((HEADING_MARKER if current_is_heading else "") + cleaned)

    return [paragraph for paragraph in paragraphs if paragraph]


def strip_heading_marker(text: str) -> str:
    return text.lstrip(HEADING_MARKER)


def looks_like_heading(text: str) -> bool:
    compact = normalize_inline(text)
    if compact.startswith(HEADING_MARKER):
        return True
    compact = strip_heading_marker(compact)
    if not compact or len(compact) > 14:
        return False
    if any(mark in compact for mark in "，。！？；：,!?;:"):
        return False
    if CREDIT_LINE_RE.fullmatch(compact):
        return False
    if re.fullmatch(r"(?:代?序|前言|后记|跋|引言|附录|第[一二三四五六七八九十百零〇0-9]+[章节部篇卷])", compact):
        return True
    return bool(CJK_RE.search(compact)) and len(compact) <= 10


def has_strong_sentence_end(text: str) -> bool:
    compact = normalize_inline(text).rstrip(TRAILING_CLOSERS)
    return bool(compact) and compact[-1] in STRONG_SENTENCE_END


def should_merge_false_paragraph_break(left: str, right: str, reading_profile: str = "prose") -> bool:
    left = normalize_inline(left)
    right = normalize_inline(right)
    if not left or not right:
        return False
    if looks_like_heading(left):
        return False
    if reading_profile == "novel":

        if has_unclosed_dialogue_quote(left) and not normalize_inline(right).startswith(tuple(DIALOGUE_OPENERS)):
            return True
        if is_dialogue_text(left) or is_dialogue_text(right):
            return False
    if has_strong_sentence_end(left):
        return False
    if left[-1] in OPEN_PUNCTUATION:
        return True


    if len(left) >= 28:
        return True

    if len(left) >= 10 and (CJK_RE.search(left[-1]) or left[-1].isalnum()):
        if CJK_RE.search(right[0]) or right[0].isalnum() or right[0] in CLOSE_PUNCTUATION:
            return True
    return False


def repair_paragraph_boundaries(paragraphs: Sequence[str], reading_profile: str = "prose") -> list[str]:
    repaired: list[str] = []
    for paragraph in paragraphs:
        current = normalize_inline(paragraph)
        if not current:
            continue
        if repaired and should_merge_false_paragraph_break(repaired[-1], current, reading_profile):
            repaired[-1] = normalize_inline(smart_join(repaired[-1], current))
        else:
            repaired.append(current)
    return repaired


def split_completed_page_prefix(text: str) -> tuple[str, str]:

    compact = normalize_inline(strip_heading_marker(text))
    if not compact:
        return "", ""
    last_end = -1
    index = 0
    while index < len(compact):
        char = compact[index]
        terminal = char in PAGE_FINAL_SENTENCE_END or (char == "…" and index > 0 and compact[index - 1] == "…")
        if terminal:
            end = index + 1
            while end < len(compact) and compact[end] in TRAILING_CLOSERS:
                end += 1
            last_end = end
            index = end
            continue
        index += 1
    if last_end < 0:
        return "", compact
    return compact[:last_end].strip(), compact[last_end:].strip()


def merge_continuous_page_paragraphs(
    pages: Sequence[PageResult],
    selected_pages: Sequence[int],
) -> None:
\
\
\
\
\

    for index in range(len(pages) - 1):
        left_page = pages[index]
        right_page = pages[index + 1]
        contiguous = selected_pages[index] + 1 == selected_pages[index + 1]
        if not contiguous:
            left_page.warnings.append(f"hard_page_boundary_before_{right_page.page_number}")
            continue
        if left_page.page_type in {"blank", "toc", "title"} or right_page.page_type in {"blank", "toc", "title"}:
            continue
        if not left_page.paragraphs or not right_page.paragraphs:
            continue
        left_index = len(left_page.paragraphs) - 1
        right_index = 0
        left = left_page.paragraphs[left_index]
        right = right_page.paragraphs[right_index]
        if left.startswith(HEADING_MARKER) or right.startswith(HEADING_MARKER):
            continue
        prefix, tail = split_completed_page_prefix(left)
        if not tail:
            continue
        merged = clean_reading_text(smart_join(tail, right), drop_inline_notes=False)
        if not merged:
            continue
        if prefix:
            left_page.paragraphs[left_index] = prefix
        else:
            left_page.paragraphs.pop(left_index)
        right_page.paragraphs[right_index] = merged
        left_page.warnings.append(f"cross_page_tail_moved_to_{right_page.page_number}")
        right_page.warnings.append(f"cross_page_tail_received_from_{left_page.page_number}")


def split_sentences(text: str) -> list[str]:
    compact = normalize_inline(text)
    if not compact:
        return []
    sentences: list[str] = []
    start = 0
    index = 0
    while index < len(compact):
        if compact[index] in STRONG_SENTENCE_END:
            end = index + 1
            while end < len(compact) and compact[end] in TRAILING_CLOSERS:
                end += 1
            sentence = compact[start:end].strip()
            if sentence:
                sentences.append(sentence)
            start = end
            index = end
            continue
        index += 1
    tail = compact[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def split_long_sentence(sentence: str, max_chars: int, min_chars: int) -> list[str]:

    sentence = normalize_inline(sentence)
    if len(sentence) <= max_chars:
        return [sentence]
    pieces: list[str] = []
    remaining = sentence
    soft_marks = "，、；：,;:"
    overflow = max(48, max_chars // 3)
    absolute_limit = max_chars + overflow
    while len(remaining) > max_chars:
        lower = min(min_chars, max_chars - 1)
        backward = [
            index + 1
            for index, char in enumerate(remaining[: max_chars + 1])
            if char in soft_marks and index + 1 >= lower
        ]
        if backward:
            cut = backward[-1]
        else:
            forward = next(
                (
                    index + 1
                    for index, char in enumerate(remaining[max_chars:absolute_limit], start=max_chars)
                    if char in soft_marks
                ),
                None,
            )
            if forward is None:


                break
            cut = forward
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        if pieces and len(remaining) < max(12, min_chars // 2):
            pieces[-1] = normalize_inline(smart_join(pieces[-1], remaining))
        else:
            pieces.append(remaining)
    return [piece for piece in pieces if piece]


def paragraphs_to_speech_chunks(
    paragraphs: Sequence[str],
    min_chars: int,
    max_chars: int,
    reading_profile: str = "prose",
) -> list[str]:
    chunks: list[str] = []
    current = ""

    def flush() -> None:
        nonlocal current
        cleaned = normalize_inline(current)
        if cleaned:
            chunks.append(cleaned)
        current = ""

    for paragraph in paragraphs:
        paragraph = normalize_inline(paragraph)
        if not paragraph:
            continue
        if looks_like_heading(paragraph):
            flush()
            chunks.append(strip_heading_marker(paragraph))
            continue
        paragraph = strip_heading_marker(paragraph)
        if reading_profile == "novel" and is_dialogue_text(paragraph):
            flush()


            dialogue_parts: list[str] = []
            for sentence in split_sentences(paragraph):
                dialogue_parts.extend(split_long_sentence(sentence, max_chars, min_chars))
            chunks.extend(dialogue_parts or [paragraph])
            continue
        sentences: list[str] = []
        for sentence in split_sentences(paragraph):
            sentences.extend(split_long_sentence(sentence, max_chars, min_chars))
        for sentence in sentences:
            if not current:
                current = sentence
                continue
            candidate = normalize_inline(smart_join(current, sentence))
            if len(candidate) <= max_chars:
                current = candidate
            else:
                flush()
                current = sentence



        flush()
    flush()
    return chunks



def choose_auto_content_start(pages: Sequence[PageResult], keep_title_page: bool) -> int:
\
\
\
\
\

    if not pages:
        return 0
    early_limit = max(1, math.ceil(len(pages) * 0.45))
    toc_indices = [index for index, page in enumerate(pages[:early_limit]) if page.page_type == "toc"]
    search_from = toc_indices[-1] + 1 if toc_indices else 0

    first_body: int | None = None
    title_before_body: int | None = None
    for index in range(search_from, len(pages)):
        page = pages[index]
        if page.page_type == "title":
            title_before_body = index
            continue
        if page.page_type == "blank":
            continue
        if page.page_type == "body":
            first_body = index
            break
        if page.page_type not in {"toc", "diagram"}:
            title_before_body = None
    if first_body is None:
        return 0
    if keep_title_page and title_before_body is not None and title_before_body < first_body:
        return title_before_body
    return first_body


def apply_content_start_policy(
    pages: Sequence[PageResult],
    selected_pages: Sequence[int],
    mode: str,
    explicit_page: int | None,
    keep_title_page: bool,
) -> int:
    if not pages or mode == "all":
        return 0
    if mode == "page":
        target = explicit_page or 1
        start_index = next((index for index, source_index in enumerate(selected_pages) if source_index + 1 >= target), len(pages))
    else:
        start_index = choose_auto_content_start(pages, keep_title_page)
    for index, page in enumerate(pages):
        if index < start_index:
            page.paragraphs = []
            page.speech_chunks = []
            page.text = ""
            page.warnings.append("speech_skipped_before_content_start")
    if pages:
        pages[min(start_index, len(pages) - 1)].warnings.append(f"content_start_index_{start_index}")
    return start_index


def write_hidden_page_text(
    page: pymupdf.Page,
    text: str,
    font_name: str,
    preferred_font_size: float,
) -> None:
    text = safe_text(text)
    if not text.strip():
        return
    margin = max(10.0, min(page.rect.width, page.rect.height) * 0.025)
    rect = pymupdf.Rect(margin, margin, page.rect.width - margin, page.rect.height - margin)
    font_size = preferred_font_size
    while font_size >= 1.2:
        result = page.insert_textbox(
            rect,
            text,
            fontsize=font_size,
            fontname=font_name,
            render_mode=3,
            overlay=True,
            lineheight=1.15,
        )
        if result >= 0:
            return
        font_size -= 0.25

    page.insert_text(
        pymupdf.Point(margin, margin + 4),
        text.replace("\n", " "),
        fontsize=1.0,
        fontname=font_name,
        render_mode=3,
        overlay=True,
    )


def save_text_output(path: Path, pages: Sequence[PageResult]) -> None:


    chunks = [safe_text(page.text).strip() for page in pages if safe_text(page.text).strip()]
    path.write_text("\n\n".join(chunks).rstrip() + "\n", encoding="utf-8")


def collect_review_items(page: PageResult, threshold: float) -> list[dict[str, Any]]:
    kept_indices = {line.source_index for line in page.kept_lines}
    items: list[dict[str, Any]] = []
    for line in page.raw_lines:
        if line.score >= threshold:
            continue
        disposition = "kept" if line.source_index in kept_indices else (line.dropped_reason or "filtered")
        items.append({
            "page_number": page.page_number,
            "text": line.text,
            "score": round(line.score, 4),
            "box": list(line.box),
            "disposition": disposition,
        })
    return items


def save_review_output(path: Path, pages: Sequence[PageResult], threshold: float) -> None:
    sections: list[str] = []
    for page in pages:
        items = collect_review_items(page, threshold)
        if not items:
            continue
        lines = [f"第 {page.page_number} 页 · 平均置信度 {page.average_confidence:.3f}"]
        for item in items:
            lines.append(
                f"[{item['score']:.3f}] {item['text']}  ({item['disposition']})"
            )
        sections.append("\n".join(lines))
    if sections:
        content = (
            "PDF Text Repair 低置信度复核清单\n"
            f"阈值：{threshold:.2f}。本文件只提示人工复核，不会自动改字。\n\n"
            + "\n\n".join(sections)
            + "\n"
        )
    else:
        content = (
            "PDF Text Repair 低置信度复核清单\n"
            f"阈值：{threshold:.2f}。未发现低于阈值的 OCR 行。\n"
        )
    path.write_text(safe_text(content), encoding="utf-8")


def save_debug_report(path: Path, pages: Sequence[PageResult], config: PipelineConfig) -> None:
    review_queue = [
        item
        for page in pages
        for item in collect_review_items(page, config.review_score_threshold)
    ]
    payload = {
        "engine": "PaddleOCR PP-OCRv6",
        "config": asdict(config),
        "review_queue": review_queue,
        "pages": [
            {
                "page_number": page.page_number,
                "page_type": page.page_type,
                "average_confidence": page.average_confidence,
                "warnings": page.warnings,
                "low_confidence_lines": collect_review_items(page, config.review_score_threshold),
                "paragraphs": page.paragraphs,
                "speech_chunks": page.speech_chunks,
                "text": page.text,
                "raw_lines": [asdict(line) for line in page.raw_lines],
                "kept_lines": [asdict(line) for line in page.kept_lines],
            }
            for page in pages
        ],
    }
    payload = sanitize_json_value(payload)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def parse_pages(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(total))
    selected: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_text, end_text = part.split("-", 1)
            start, end = int(start_text), int(end_text)
            selected.update(range(min(start, end), max(start, end) + 1))
        else:
            selected.add(int(part))
    result = sorted(page - 1 for page in selected if 1 <= page <= total)
    if not result:
        raise ValueError("--pages did not select any valid page")
    return result


def paddle_language(language_codes: Sequence[str]) -> str:
    codes = set(language_codes)
    if "jpn" in codes:
        return "japan"
    if "chi_tra" in codes and "chi_sim" not in codes:
        return "chinese_cht"
    if "chi_sim" in codes or "chi_tra" in codes:
        return "ch"
    if "fra" in codes:
        return "fr"
    return "en"


def model_source_order() -> list[str]:
    configured = os.environ.get(
        "PDF_TEXT_REPAIR_MODEL_SOURCES",
        "modelscope,bos,huggingface",
    )
    preferred = os.environ.get("PADDLE_PDX_MODEL_SOURCE", "").strip().lower()
    sources = ([preferred] if preferred else []) + [
        item.strip().lower() for item in configured.split(",") if item.strip()
    ]
    allowed = {"modelscope", "bos", "huggingface", "aistudio"}
    ordered: list[str] = []
    for source in sources:
        if source in allowed and source not in ordered:
            ordered.append(source)
    return ordered or ["modelscope", "bos", "huggingface"]


def model_cache_complete(path: Path) -> bool:
    if not path.is_dir():
        return False
    files = [item for item in path.rglob("*") if item.is_file()]
    names = {item.name.lower() for item in files}
    has_config = any(
        name in names
        for name in (
            "inference.yml",
            "inference.yaml",
            "model.yml",
            "model.yaml",
        )
    )
    has_graph = any(
        item.suffix.lower() in {".json", ".pdmodel"} for item in files
    )
    has_params = any(
        item.name.lower().endswith((".pdiparams", ".pdparams")) for item in files
    )
    return has_config and has_graph and has_params


def clear_incomplete_model_cache(model_names: Sequence[str]) -> None:
    cache_root = Path.home() / ".paddlex" / "official_models"
    for model_name in model_names:
        model_path = cache_root / model_name
        if model_path.exists() and not model_cache_complete(model_path):
            log(f"PADDLE_CACHE_REMOVE incomplete {model_path}")
            shutil.rmtree(model_path, ignore_errors=True)


def create_ocr(config: PipelineConfig) -> Any:
    try:
        from paddleocr import PaddleOCR
    except Exception as error:
        raise RuntimeError(
            "PaddleOCR is unavailable. Run scripts/install-ocr-engine-macos.command again."
        ) from error

    model_prefix = {
        "tiny": "PP-OCRv6_tiny",
        "small": "PP-OCRv6_small",
        "medium": "PP-OCRv6_medium",
    }[config.model_tier]
    model_names = [f"{model_prefix}_det", f"{model_prefix}_rec"]
    kwargs: dict[str, Any] = {


        "ocr_version": "PP-OCRv6",
        "text_detection_model_name": model_names[0],
        "text_recognition_model_name": model_names[1],
        "use_doc_orientation_classify": config.use_orientation,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "text_rec_score_thresh": 0.0,
        "device": "cpu",
    }
    try:
        import paddle
        log("PADDLE_BACKEND paddle_static")
    except Exception:
        try:
            import onnxruntime
        except Exception as error:
            raise RuntimeError(
                "Neither PaddlePaddle nor ONNX Runtime is installed for PaddleOCR."
            ) from error
        kwargs["engine"] = "onnxruntime"
        log("PADDLE_BACKEND onnxruntime")

    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")



    clear_incomplete_model_cache(model_names)
    last_error: Exception | None = None
    sources = model_source_order()
    for attempt, source in enumerate(sources, start=1):
        os.environ["PADDLE_PDX_MODEL_SOURCE"] = source
        log(f"PADDLE_MODEL_SOURCE {source} · attempt {attempt}/{len(sources)}")
        try:
            ocr = PaddleOCR(**kwargs)
            log(f"PADDLE_MODEL_READY {model_prefix} · source={source}")
            return ocr
        except Exception as error:
            last_error = error
            message = str(error).replace("\n", " ")
            log(f"PADDLE_MODEL_SOURCE_FAILED {source}: {type(error).__name__}: {message}")
            clear_incomplete_model_cache(model_names)

    raise RuntimeError(
        "PP-OCRv6 model download failed from all configured sources "
        f"({', '.join(sources)}). Re-run the model preparation script to resume. "
        f"Last error: {last_error}"
    )


def predict_page(ocr: Any, image_path: Path) -> Any:
    result = ocr.predict(str(image_path))
    iterator = iter(result)
    try:
        return next(iterator)
    except StopIteration as error:
        raise RuntimeError("PaddleOCR returned no result for a rendered page") from error


def run_pipeline(args: argparse.Namespace) -> int:
    input_path = Path(args.input_pdf).expanduser().resolve()
    output_path = Path(args.output_pdf).expanduser().resolve()
    if not input_path.is_file():
        raise FileNotFoundError(f"Input PDF does not exist: {input_path}")
    if output_path.exists():
        raise FileExistsError(f"Output already exists: {output_path}")

    source = pymupdf.open(input_path)
    selected_pages = parse_pages(args.pages, source.page_count)
    language_codes = [part for part in args.languages.split("+") if part]
    config = PipelineConfig(
        dpi=args.dpi,
        language=paddle_language(language_codes),
        model_tier=args.model_tier,
        score_threshold=args.score_threshold,
        filter_margins=args.filter_margins,
        drop_diagram_labels=args.drop_diagram_labels,
        drop_footnotes=not args.include_footnotes,
        skip_toc=not args.read_toc,
        drop_running_headers=not args.keep_running_headers,
        drop_citation_lines=not args.keep_citation_lines,
        drop_credit_lines=not args.keep_credit_lines,
        use_orientation=args.use_orientation,
        font_name=args.font_name,
        font_size=args.font_size,
        min_chunk_chars=args.min_chunk_chars,
        max_chunk_chars=args.max_chunk_chars,
        merge_continuous_pages=not args.no_merge_continuous_pages,
        review_score_threshold=args.review_score_threshold,
        reading_profile=args.reading_profile,
        content_start_mode=args.content_start_mode,
        content_start_page=args.content_start_page,
        keep_title_page=not args.skip_title_page,
    )

    os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "modelscope")
    os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
    log(f"PADDLE_INIT PP-OCRv6 {config.model_tier} · language={config.language}")
    ocr = create_ocr(config)
    pages: list[PageResult] = []

    with tempfile.TemporaryDirectory(prefix="pdf-text-repair-paddle-") as temp_dir_text:
        temp_dir = Path(temp_dir_text)
        for sequence_index, page_index in enumerate(selected_pages, start=1):
            page = source[page_index]
            scale = config.dpi / 72.0
            pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            image_path = temp_dir / f"page-{page_index + 1:05d}.png"
            pix.save(image_path)
            log(f"PADDLE_PAGE {sequence_index}/{len(selected_pages)} · source page {page_index + 1}")
            result = predict_page(ocr, image_path)
            raw_lines = extract_lines(result, config.score_threshold)
            available = [line for line in raw_lines if line.dropped_reason is None]
            page_type = detect_page_type(available, pix.width, pix.height)
            scores = [line.score for line in available]
            average_confidence = statistics.fmean(scores) if scores else 0.0
            warnings: list[str] = []
            sanitized_lines = sum(1 for line in raw_lines if line.unicode_sanitized)
            if sanitized_lines:
                warnings.append(f"unicode_sanitized_lines_{sanitized_lines}")
                log(f"PADDLE_UNICODE_SANITIZED page {page_index + 1} · {sanitized_lines} OCR line(s)")
            if available and average_confidence < 0.78:
                warnings.append("low_average_confidence")
            pages.append(
                PageResult(
                    page_number=page_index + 1,
                    image_width=pix.width,
                    image_height=pix.height,
                    page_type=page_type,
                    average_confidence=average_confidence,
                    raw_lines=raw_lines,
                    kept_lines=[],
                    paragraphs=[],
                    speech_chunks=[],
                    text="",
                    warnings=warnings,
                )
            )

    repeated_margins = collect_repeated_margins(pages)
    for page in pages:
        page.kept_lines = filter_page_lines(page, repeated_margins, config)
        refine_sparse_title_page(page)

        if page.page_type == "toc" and config.skip_toc:
            page.paragraphs = []
            page.speech_chunks = []
            page.text = ""
            page.warnings.append("speech_skipped_toc")
            continue

        raw_paragraphs = lines_to_paragraphs(
            page.kept_lines,
            page.image_width,
            page.page_type,
        )
        page_profile = resolve_reading_profile(raw_paragraphs, config.reading_profile)
        repaired = repair_paragraph_boundaries(raw_paragraphs, page_profile)
        page.paragraphs = [
            cleaned
            for paragraph in repaired
            if (cleaned := clean_reading_text(paragraph, config.drop_footnotes))
        ]

    content_start_index = apply_content_start_policy(
        pages,
        selected_pages,
        config.content_start_mode,
        config.content_start_page,
        config.keep_title_page,
    )
    log(
        f"PADDLE_CONTENT_START mode={config.content_start_mode} · "
        f"result-index={content_start_index} · source-page={pages[content_start_index].page_number if pages else 0}"
    )

    if config.merge_continuous_pages:
        merge_continuous_page_paragraphs(pages, selected_pages)

    for page in pages:
        if page.page_type == "toc" and config.skip_toc:
            continue
        page_profile = resolve_reading_profile(page.paragraphs, config.reading_profile)
        page.speech_chunks = paragraphs_to_speech_chunks(
            page.paragraphs,
            config.min_chunk_chars,
            config.max_chunk_chars,
            page_profile,
        )
        page.warnings.append(f"reading_profile_{page_profile}")
        page.paragraphs = [strip_heading_marker(item) for item in page.paragraphs]
        page.text = "\n".join(page.speech_chunks).strip()
        if page.page_type != "blank" and page.page_type != "toc" and len(page.text) < 6:
            page.warnings.append("very_little_text")
        log(
            f"PADDLE_LAYOUT page {page.page_number} · {page.page_type} · "
            f"{len(page.kept_lines)} lines · confidence {page.average_confidence:.3f}"
        )

    output = pymupdf.open()
    for result_index, source_page_index in enumerate(selected_pages):
        output.insert_pdf(source, from_page=source_page_index, to_page=source_page_index)
        out_page = output[result_index]
        write_hidden_page_text(
            out_page,
            pages[result_index].text,
            config.font_name,
            config.font_size,
        )
    safe_metadata = {safe_text(key): ("" if value is None else safe_text(value)) for key, value in source.metadata.items()}
    output.set_metadata(safe_metadata)
    output.save(output_path, garbage=3, deflate=True)
    output.close()
    source.close()

    if args.text_output:
        save_text_output(Path(args.text_output), pages)
    if args.debug_json:
        save_debug_report(Path(args.debug_json), pages, config)
    if args.review_output:
        save_review_output(Path(args.review_output), pages, config.review_score_threshold)
    low_confidence_pages = [page.page_number for page in pages if "low_average_confidence" in page.warnings]
    if low_confidence_pages:
        log("PADDLE_REVIEW low-confidence pages: " + ", ".join(map(str, low_confidence_pages)))
    log(f"PADDLE_DONE {output_path}")
    return 0


def self_test() -> int:
    lines = [
        OcrLine("星河图书馆", 0.98, (200, 120, 650, 155), 0),
        OcrLine("3", 0.99, (900, 121, 925, 154), 1),
        OcrLine("序言", 0.97, (230, 180, 320, 215), 2),
        OcrLine("5", 0.99, (900, 181, 925, 214), 3),
    ]
    rows = cluster_rows(lines)
    texts = [row_text(row, 1000, toc=True) for row in rows]
    assert texts == ["星河图书馆 …… 3", "序言 …… 5"], texts
    assert detect_page_type([OcrLine("目录", 0.99, (450, 50, 550, 90), 99)] + lines, 1000, 1400) == "toc"

    page = PageResult(
        page_number=8,
        image_width=1000,
        image_height=1400,
        page_type="toc",
        average_confidence=0.98,
        raw_lines=[
            OcrLine("8", 0.99, (490, 1360, 510, 1385), 0),
            OcrLine("星河图书馆", 0.98, (200, 120, 650, 155), 1),
            OcrLine("3", 0.99, (900, 121, 925, 154), 2),
        ],
        kept_lines=[],
        paragraphs=[],
        speech_chunks=[],
        text="",
        warnings=[],
    )
    config = PipelineConfig(
        dpi=300,
        language="ch",
        model_tier="medium",
        score_threshold=0.45,
        filter_margins=True,
        drop_diagram_labels=True,
        drop_footnotes=True,
        skip_toc=True,
        drop_running_headers=True,
        drop_citation_lines=True,
        drop_credit_lines=True,
        use_orientation=True,
        font_name="china-s",
        font_size=3.2,
        min_chunk_chars=100,
        max_chunk_chars=220,
        merge_continuous_pages=True,
        review_score_threshold=REVIEW_SCORE_THRESHOLD,
        reading_profile="auto",
        content_start_mode="all",
        content_start_page=None,
        keep_title_page=True,
    )
    kept = filter_page_lines(page, set(), config)
    assert [line.text for line in kept] == ["星河图书馆", "3"]

    body_page = PageResult(
        page_number=12,
        image_width=1000,
        image_height=1400,
        page_type="body",
        average_confidence=0.98,
        raw_lines=[
            OcrLine("概率", 0.99, (120, 200, 220, 235), 0),
            OcrLine("论和常理所不容的危险，我们现摘录", 0.99, (120, 252, 820, 287), 1),
            OcrLine("这是下一段。", 0.99, (175, 320, 430, 355), 2),
            OcrLine("①这是一条不应朗读的脚注。", 0.99, (120, 1120, 720, 1148), 3),
            OcrLine("脚注的第二行。", 0.99, (120, 1155, 520, 1183), 4),
            OcrLine("57测试章节", 0.99, (360, 1260, 650, 1288), 5),
        ],
        kept_lines=[],
        paragraphs=[],
        speech_chunks=[],
        text="",
        warnings=[],
    )
    body_kept = filter_page_lines(body_page, {stable_signature("57测试章节")}, config)
    assert [line.text for line in body_kept] == ["概率", "论和常理所不容的危险，我们现摘录", "这是下一段。"]
    body_paragraphs = lines_to_paragraphs(body_kept, 1000, "body")
    assert body_paragraphs == ["概率论和常理所不容的危险，我们现摘录", "这是下一段。"], body_paragraphs
    assert is_diagram_only_text("x1 y1 x2 x3 x4 z y2 x5")
    assert is_diagram_only_text("yl")
    assert is_diagram_only_text("(x3")
    assert not is_diagram_only_text("例如x3、y1和z三个节点")

    repaired = repair_paragraph_boundaries([
        "可以参见示例出版社出版的《示",
        "例集》①，其编排遵循了相当严格的时间顺序。",
        "序言",
        "这个集子里的七篇故事不需要很多诠释。",
        "我归诸他的一份作品清单不太有趣，但也不是毫无根",
        "据的，那是他的心灵历程的图解……",
    ])
    assert repaired == [
        "可以参见示例出版社出版的《示例集》①，其编排遵循了相当严格的时间顺序。",
        "序言",
        "这个集子里的七篇故事不需要很多诠释。",
        "我归诸他的一份作品清单不太有趣，但也不是毫无根据的，那是他的心灵历程的图解……",
    ], repaired
    chunks = paragraphs_to_speech_chunks(repaired, 40, 90)
    assert all(len(chunk) <= 140 for chunk in chunks), chunks

    cleaned = clean_reading_text(
        "可以参见他的《示例集》①，并阅读《〈内部标题>的说明》(这一说明)。",
        drop_inline_notes=True,
    )
    assert cleaned == "可以参见他的《示例集》，并阅读《〈内部标题〉的说明》（这一说明）。", cleaned
    no_hard_word_split = split_long_sentence("这是一段没有任何标点但绝不能把评论两个字从中间拆开的连续中文文字", 12, 8)
    assert no_hard_word_split == ["这是一段没有任何标点但绝不能把评论两个字从中间拆开的连续中文文字"], no_hard_word_split

    left_page = PageResult(
        page_number=38, image_width=1000, image_height=1400, page_type="body",
        average_confidence=0.96, raw_lines=[], kept_lines=[],
        paragraphs=["他闭上苍白的眼睑睡觉，不是由于疲惫，而是出于意志的决定，他知"],
        speech_chunks=[], text="", warnings=[],
    )
    right_page = PageResult(
        page_number=39, image_width=1000, image_height=1400, page_type="body",
        average_confidence=0.96, raw_lines=[], kept_lines=[],
        paragraphs=["道自己必须完成这场梦。第二段开始。"],
        speech_chunks=[], text="", warnings=[],
    )
    merge_continuous_page_paragraphs([left_page, right_page], [37, 38])
    assert left_page.paragraphs == [], left_page.paragraphs
    assert right_page.paragraphs == ["他闭上苍白的眼睑睡觉，不是由于疲惫，而是出于意志的决定，他知道自己必须完成这场梦。第二段开始。"], right_page.paragraphs

    hard_left = PageResult(
        page_number=12, image_width=1000, image_height=1400, page_type="body",
        average_confidence=0.96, raw_lines=[], kept_lines=[], paragraphs=["他知"],
        speech_chunks=[], text="", warnings=[],
    )
    hard_right = PageResult(
        page_number=47, image_width=1000, image_height=1400, page_type="body",
        average_confidence=0.96, raw_lines=[], kept_lines=[], paragraphs=["道另一件事。"],
        speech_chunks=[], text="", warnings=[],
    )
    merge_continuous_page_paragraphs([hard_left, hard_right], [11, 46])
    assert hard_left.paragraphs == ["他知"] and hard_right.paragraphs == ["道另一件事。"]
    assert "hard_page_boundary_before_47" in hard_left.warnings

    credit = OcrLine("甲某著", 0.99, (300, 900, 620, 935), 6)
    assert is_credit_line(credit, 1000, 1400)

    vertical_title = merge_vertical_title_rows([
        [OcrLine("?", 0.60, (750, 420, 780, 450), 0)],
        [OcrLine("春", 0.99, (740, 500, 790, 560), 1)],
        [OcrLine("日", 0.99, (742, 570, 792, 630), 2)],
    ], 1000)
    assert vertical_title == ["春日"], vertical_title

    dialogue_repaired = repair_paragraph_boundaries([
        "“啊！”",
        "“有头发？”",
        "我以为汤里有什么脏东西。",
        "“不。”",
    ], "novel")
    assert dialogue_repaired == ["“啊！”", "“有头发？”", "我以为汤里有什么脏东西。", "“不。”"], dialogue_repaired
    dialogue_chunks = paragraphs_to_speech_chunks(dialogue_repaired, 40, 120, "novel")
    assert dialogue_chunks[:2] == ["“啊！”", "“有头发？”"], dialogue_chunks
    wrapped_dialogue = repair_paragraph_boundaries([
        "“您放心吧，小林不会有问题的。",
        "像他那样倔强的人，不会那么容易就放弃的。",
        "小林那种人不会轻易放弃。”",
    ], "novel")
    assert wrapped_dialogue == ["“您放心吧，小林不会有问题的。像他那样倔强的人，不会那么容易就放弃的。小林那种人不会轻易放弃。”"], wrapped_dialogue
    assert normalize_reading_punctuation("母亲说，，“也许是的。”") == "母亲说，“也许是的。”"

    auto_pages = [
        PageResult(20, 1000, 1400, "toc", 0.99, [], [], [], [], "", []),
        PageResult(21, 1000, 1400, "title", 0.99, [], [], [HEADING_MARKER + "春日"], [], "", []),
        PageResult(22, 1000, 1400, "blank", 0.99, [], [], [], [], "", []),
        PageResult(23, 1000, 1400, "body", 0.99, [], [], ["早晨，母亲在餐厅里轻快地啜了一匙子汤。"], [], "", []),
    ]
    assert choose_auto_content_start(auto_pages, True) == 1
    apply_content_start_policy(auto_pages, [19, 20, 21, 22], "auto", None, True)
    assert auto_pages[0].paragraphs == [] and auto_pages[1].paragraphs == [HEADING_MARKER + "春日"]

    joined = smart_join("甲乙", "作品")
    assert joined == "甲乙作品", joined
    assert paddle_language(["chi_sim", "eng", "fra"]) == "ch"

    malformed = "春\udcc0日\x00"
    sanitized, removed_count = sanitize_unicode_text(malformed)
    assert sanitized == "春日" and removed_count == 2, (sanitized, removed_count)
    assert normalize_inline(malformed) == "春日"
    malformed_lines = extract_lines({
        "rec_texts": [malformed],
        "rec_scores": [0.99],
        "rec_boxes": [[10, 10, 100, 40]],
    }, 0.45)
    assert len(malformed_lines) == 1
    assert malformed_lines[0].text == "春日" and malformed_lines[0].unicode_sanitized

    with tempfile.TemporaryDirectory(prefix="pdf-text-repair-self-test-") as temp_dir:
        path = Path(temp_dir) / "hidden-text.pdf"
        document = pymupdf.open()
        pdf_page = document.new_page(width=595, height=842)
        hidden_text = "目录\n星河图书馆 …… 3\n第二章 …… 5\n春\udcc0日"
        write_hidden_page_text(pdf_page, hidden_text, "china-s", 3.2)
        document.save(path)
        document.close()
        with pymupdf.open(path) as reopened:
            extracted = reopened[0].get_text()
        assert "星河图书馆" in extracted, extracted
        assert "第二章" in extracted, extracted
        assert "春日" in extracted, extracted

    print("paddle_scan_pipeline self-test passed")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdf", nargs="?")
    parser.add_argument("output_pdf", nargs="?")
    parser.add_argument("--languages", default="chi_sim+eng")
    parser.add_argument("--dpi", type=int, default=300)
    parser.add_argument("--model-tier", choices=("tiny", "small", "medium"), default="medium")
    parser.add_argument("--score-threshold", type=float, default=0.45)
    parser.add_argument("--font-name", default="china-s")
    parser.add_argument("--font-size", type=float, default=3.2)
    parser.add_argument("--filter-margins", action="store_true")
    parser.add_argument("--drop-diagram-labels", action="store_true")
    parser.add_argument("--include-footnotes", action="store_true", help="keep bottom-page footnotes in the Readest layer")
    parser.add_argument("--read-toc", action="store_true", help="include table-of-contents pages in the Readest layer")
    parser.add_argument("--keep-running-headers", action="store_true", help="keep page numbers and running headers")
    parser.add_argument("--keep-citation-lines", action="store_true", help="keep short epigraph/source attribution lines")
    parser.add_argument("--keep-credit-lines", action="store_true", help="keep author/translator/editor credit lines")
    parser.add_argument("--min-chunk-chars", type=int, default=100, help="preferred minimum Readest chunk length")
    parser.add_argument("--max-chunk-chars", type=int, default=220, help="preferred maximum Readest chunk length")
    parser.add_argument("--use-orientation", action="store_true")
    parser.add_argument("--text-output")
    parser.add_argument("--debug-json")
    parser.add_argument("--review-output", help="write a human-readable low-confidence review list")
    parser.add_argument("--review-score-threshold", type=float, default=REVIEW_SCORE_THRESHOLD)
    parser.add_argument("--no-merge-continuous-pages", action="store_true", help="keep every source page as a hard speech boundary")
    parser.add_argument("--reading-profile", choices=("auto", "prose", "novel"), default="auto", help="preserve fiction dialogue turns or use prose chunking")
    parser.add_argument("--content-start-mode", choices=("all", "auto", "page"), default="all", help="include all pages, auto-detect the main text, or start at a source page")
    parser.add_argument("--content-start-page", type=int, help="1-based source page used with --content-start-mode page")
    parser.add_argument("--skip-title-page", action="store_true", help="when auto-detecting main text, begin at body text instead of the preceding chapter title page")
    parser.add_argument("--pages", help="1-based page list/ranges, e.g. 4,7-9,12")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare-models", action="store_true", help="download and validate OCR models, then exit")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.self_test:
        return self_test()
    if args.prepare_models:
        language_codes = [part for part in args.languages.split("+") if part]
        config = PipelineConfig(
            dpi=args.dpi,
            language=paddle_language(language_codes),
            model_tier=args.model_tier,
            score_threshold=args.score_threshold,
            filter_margins=args.filter_margins,
            drop_diagram_labels=args.drop_diagram_labels,
            drop_footnotes=not args.include_footnotes,
            skip_toc=not args.read_toc,
            drop_running_headers=not args.keep_running_headers,
            drop_citation_lines=not args.keep_citation_lines,
            drop_credit_lines=not args.keep_credit_lines,
            use_orientation=args.use_orientation,
            font_name=args.font_name,
            font_size=args.font_size,
            min_chunk_chars=args.min_chunk_chars,
            max_chunk_chars=args.max_chunk_chars,
            merge_continuous_pages=not args.no_merge_continuous_pages,
            review_score_threshold=args.review_score_threshold,
            reading_profile=args.reading_profile,
            content_start_mode=args.content_start_mode,
            content_start_page=args.content_start_page,
            keep_title_page=not args.skip_title_page,
        )
        log(f"PADDLE_PREPARE PP-OCRv6 {config.model_tier}")
        create_ocr(config)
        log("PADDLE_PREPARE_DONE")
        return 0
    if not args.input_pdf or not args.output_pdf:
        parser.error(
            "input_pdf and output_pdf are required unless --self-test or --prepare-models is used"
        )
    if not 150 <= args.dpi <= 600:
        parser.error("--dpi must be between 150 and 600")
    if not 0.0 <= args.score_threshold <= 1.0:
        parser.error("--score-threshold must be between 0 and 1")
    if not 0.0 <= args.review_score_threshold <= 1.0:
        parser.error("--review-score-threshold must be between 0 and 1")
    if args.content_start_mode == "page" and (args.content_start_page is None or args.content_start_page < 1):
        parser.error("--content-start-page must be at least 1 when --content-start-mode page is used")
    if not 20 <= args.min_chunk_chars <= 400:
        parser.error("--min-chunk-chars must be between 20 and 400")
    if not args.min_chunk_chars < args.max_chunk_chars <= 800:
        parser.error("--max-chunk-chars must be greater than min and at most 800")
    try:
        return run_pipeline(args)
    except KeyboardInterrupt:
        log("PADDLE_CANCELLED")
        return 130
    except Exception as error:
        log(f"PADDLE_ERROR {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
