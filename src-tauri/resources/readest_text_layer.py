#!/usr/bin/env python3
\
\
\
\
\
\
\


from __future__ import annotations

import argparse
import math
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import pymupdf

CJK_RANGE = r"\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
CJK_CHAR_RE = re.compile(f"[{CJK_RANGE}]")
LONE_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")
DISALLOWED_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
OPEN_PUNCTUATION = "“‘（《〈【〔［｛(<\"'"
CLOSE_PUNCTUATION = "，。！？；：、）】》〉〕］｝…—,.!?;:)]}>%％℃°\"'"
SENTENCE_END = "。！？!?；;：:…"
PAGE_NUMBER_RE = re.compile(
    r"^(?:[-—–·•\s]*)(?:\d{1,4}|[ivxlcdm]{1,8}|第?\s*\d{1,4}\s*页)(?:[-—–·•\s]*)$",
    re.IGNORECASE,
)
DIAGRAM_LABEL_RE = re.compile(
    r"^(?:[xyzabc]\d{0,2}|[xyzabc]\d*\s*[=<>]\s*\d+|[{}\[\]()|\\/]+)$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class LayoutLine:
    text: str
    rect: pymupdf.Rect
    block_index: int
    line_index: int
    height: float


def is_cjk(character: str) -> bool:
    return bool(character and CJK_CHAR_RE.fullmatch(character))


def smart_join(left: str, right: str) -> str:
    left = left.rstrip()
    right = right.lstrip()
    if not left:
        return right
    if not right:
        return left

    last = left[-1]
    first = right[0]
    if last == "-" and first.isalpha():
        return left[:-1] + right
    if (
        is_cjk(last)
        or is_cjk(first)
        or last in OPEN_PUNCTUATION
        or first in CLOSE_PUNCTUATION
        or last in CLOSE_PUNCTUATION
    ):
        return left + right
    if last.isalnum() and first.isalnum():
        return left + " " + right
    return left + right


def normalize_inline(text: str) -> str:
    text = LONE_SURROGATE_RE.sub("", str(text))
    text = DISALLOWED_CONTROL_RE.sub("", text)
    text = (
        text.replace("\u00a0", " ")
        .replace("\u200b", "")
        .replace("\ufeff", "")
        .replace("\u00ad", "")
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(f"(?<=[{CJK_RANGE}]) +(?=[{CJK_RANGE}])", "", text)
    text = re.sub(
        f"(?<=[{CJK_RANGE}]) +(?=[，。！？；：、）】》〉〕］｝…])",
        "",
        text,
    )
    text = re.sub(
        f"(?<=[（【《〈〔［｛“‘]) +(?=[{CJK_RANGE}])",
        "",
        text,
    )
    punctuation_rules = [
        (",", "，"),
        (r"\.", "。"),
        (r"\?", "？"),
        ("!", "！"),
        (";", "；"),
        (":", "："),
    ]
    for source, target in punctuation_rules:
        pattern = rf"(?<=[{CJK_RANGE}])\s*{source}\s*(?=[{CJK_RANGE}“‘（《〈【]|$)"
        text = re.sub(pattern, target, text)
    text = re.sub(r"\s+([，。！？；：、）】》〉〕］｝…])", r"\1", text)
    text = re.sub(r"([（【《〈〔［｛“‘])\s+", r"\1", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = re.sub(r"[；;]{2,}", "；", text)
    text = re.sub(r"[：:]{2,}", "：", text)
    return re.sub(r" {2,}", " ", text).strip()


def normalize_page_text(raw: str) -> str:
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    raw = "\n".join(line.rstrip() for line in raw.splitlines())
    groups = re.split(r"\n\s*\n+", raw)
    paragraphs: list[str] = []

    for group in groups:
        lines = [normalize_inline(line) for line in group.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            continue
        paragraph = ""
        for line in lines:
            paragraph = smart_join(paragraph, line)
        paragraph = normalize_inline(paragraph)
        if paragraph:
            paragraphs.append(paragraph)

    return "\n\n".join(paragraphs)


def extract_page_text(page: pymupdf.Page) -> str:
    blocks = sorted(page.get_text("blocks"), key=lambda block: (round(block[1], 1), block[0]))
    useful_blocks = [block for block in blocks if str(block[4]).strip()]
    if not useful_blocks:
        return ""

    heights = sorted(max(1.0, block[3] - block[1]) for block in useful_blocks)
    median_height = heights[len(heights) // 2]
    paragraphs: list[str] = []
    current = ""
    previous_bottom: float | None = None

    for block in useful_blocks:
        x0, y0, _x1, y1, block_text, *_rest = block
        text = normalize_page_text(str(block_text))
        if not text:
            continue
        gap = 0.0 if previous_bottom is None else y0 - previous_bottom
        starts_new_paragraph = bool(
            current
            and (gap > max(8.0, median_height * 0.75) or x0 > page.rect.width * 0.21)
        )
        if starts_new_paragraph:
            paragraphs.append(current.strip())
            current = text
        else:
            current = smart_join(current, text)
        previous_bottom = y1

    if current.strip():
        paragraphs.append(current.strip())
    return "\n\n".join(normalize_inline(item) for item in paragraphs if item.strip())


def extract_layout_lines(page: pymupdf.Page) -> list[LayoutLine]:
    page_dict = page.get_text("dict")
    lines: list[LayoutLine] = []
    for block_index, block in enumerate(page_dict.get("blocks", [])):
        if block.get("type") != 0:
            continue
        for line_index, line in enumerate(block.get("lines", [])):
            text = ""
            span_rects: list[pymupdf.Rect] = []
            for span in line.get("spans", []):
                span_text = normalize_inline(str(span.get("text", "")))
                if not span_text:
                    continue
                text = smart_join(text, span_text)
                bbox = span.get("bbox")
                if bbox and len(bbox) == 4:
                    span_rects.append(pymupdf.Rect(bbox))
            text = normalize_inline(text)
            if not text:
                continue
            bbox = line.get("bbox")
            if bbox and len(bbox) == 4:
                rect = pymupdf.Rect(bbox)
            elif span_rects:
                rect = span_rects[0]
                for span_rect in span_rects[1:]:
                    rect |= span_rect
            else:
                continue
            lines.append(
                LayoutLine(
                    text=text,
                    rect=rect,
                    block_index=block_index,
                    line_index=line_index,
                    height=max(1.0, rect.height),
                )
            )
    return sorted(lines, key=lambda item: (round(item.rect.y0, 1), item.rect.x0))


def canonical_margin_text(text: str) -> str:
    text = normalize_inline(text).casefold()
    text = re.sub(r"\d+", "#", text)
    text = re.sub(r"[\s\W_]+", "", text, flags=re.UNICODE)
    return text


def repeated_margin_keys(
    all_lines: list[list[LayoutLine]],
    page_rects: list[pymupdf.Rect],
    header_ratio: float,
    footer_ratio: float,
) -> set[str]:
    counts: Counter[str] = Counter()
    for lines, rect in zip(all_lines, page_rects):
        seen_on_page: set[str] = set()
        header_limit = rect.height * header_ratio
        footer_limit = rect.height * (1.0 - footer_ratio)
        for line in lines:
            if line.rect.y1 <= header_limit or line.rect.y0 >= footer_limit:
                key = canonical_margin_text(line.text)
                if len(key) >= 2:
                    seen_on_page.add(key)
        counts.update(seen_on_page)
    threshold = max(3, math.ceil(len(all_lines) * 0.15))
    return {key for key, count in counts.items() if count >= threshold}


def meaningful_character_count(text: str) -> int:
    return sum(character.isalnum() or is_cjk(character) for character in text)


def should_drop_scan_line(
    line: LayoutLine,
    page_rect: pymupdf.Rect,
    repeated_keys: set[str],
    header_ratio: float,
    footer_ratio: float,
    drop_diagram_labels: bool,
) -> tuple[bool, str]:
    text = line.text.strip()
    if not text:
        return True, "empty"

    in_header = line.rect.y1 <= page_rect.height * header_ratio
    in_footer = line.rect.y0 >= page_rect.height * (1.0 - footer_ratio)
    if (in_header or in_footer) and canonical_margin_text(text) in repeated_keys:
        return True, "repeated-margin"
    if in_footer and PAGE_NUMBER_RE.fullmatch(text):
        return True, "page-number"

    characters = meaningful_character_count(text)
    if characters == 0:
        return True, "symbols"
    if drop_diagram_labels and characters <= 4:
        compact = re.sub(r"\s+", "", text)
        if DIAGRAM_LABEL_RE.fullmatch(compact):
            return True, "diagram-label"
        if line.rect.width <= page_rect.width * 0.12 and re.fullmatch(r"[A-Za-z0-9]+", compact):
            return True, "tiny-ascii-label"
    return False, ""


def looks_like_centered_title(
    line: LayoutLine,
    page_rect: pymupdf.Rect,
    median_height: float,
) -> bool:
    text_length = meaningful_character_count(line.text)
    if not 2 <= text_length <= 32 or line.height < median_height * 1.18:
        return False
    center_delta = abs(line.rect.x0 + line.rect.width / 2 - page_rect.width / 2)
    return center_delta <= page_rect.width * 0.10 and line.rect.width <= page_rect.width * 0.68


def merge_visual_rows(lines: list[LayoutLine]) -> list[LayoutLine]:
    if not lines:
        return []
    heights = sorted(line.height for line in lines)
    median_height = heights[len(heights) // 2]
    rows: list[list[LayoutLine]] = []
    for line in sorted(lines, key=lambda item: (item.rect.y0, item.rect.x0)):
        center = (line.rect.y0 + line.rect.y1) / 2
        if rows:
            previous_centers = [
                (item.rect.y0 + item.rect.y1) / 2 for item in rows[-1]
            ]
            row_center = sum(previous_centers) / len(previous_centers)
            vertical_overlap = any(
                min(line.rect.y1, item.rect.y1) - max(line.rect.y0, item.rect.y0)
                > min(line.height, item.height) * 0.35
                for item in rows[-1]
            )
            if abs(center - row_center) <= median_height * 0.45 or vertical_overlap:
                rows[-1].append(line)
                continue
        rows.append([line])

    merged: list[LayoutLine] = []
    for row_index, row in enumerate(rows):
        row = sorted(row, key=lambda item: item.rect.x0)
        text = ""
        rect = row[0].rect
        for item in row:
            text = smart_join(text, item.text)
            rect |= item.rect
        merged.append(
            LayoutLine(
                text=normalize_inline(text),
                rect=rect,
                block_index=min(item.block_index for item in row),
                line_index=row_index,
                height=max(item.height for item in row),
            )
        )
    return merged


def scan_layout_text(
    lines: list[LayoutLine],
    page_rect: pymupdf.Rect,
    repeated_keys: set[str],
    header_ratio: float,
    footer_ratio: float,
    drop_diagram_labels: bool,
    minimum_characters: int,
) -> tuple[str, dict[str, int]]:
    stats: defaultdict[str, int] = defaultdict(int)
    kept: list[LayoutLine] = []
    for line in lines:
        drop, reason = should_drop_scan_line(
            line,
            page_rect,
            repeated_keys,
            header_ratio,
            footer_ratio,
            drop_diagram_labels,
        )
        if drop:
            stats[reason] += 1
        else:
            kept.append(line)

    if not kept:
        return "", dict(stats)

    kept = merge_visual_rows(kept)
    if drop_diagram_labels:
        merged_kept: list[LayoutLine] = []
        for line in kept:
            compact = re.sub(r"\s+", "", line.text)
            has_cjk = bool(CJK_CHAR_RE.search(compact))
            mostly_ascii = bool(compact) and sum(ord(ch) < 128 for ch in compact) / len(compact) >= 0.80
            diagram_row = bool(
                not has_cjk
                and mostly_ascii
                and meaningful_character_count(compact) <= 20
                and line.rect.width <= page_rect.width * 0.45
                and page_rect.height * 0.20 <= line.rect.y0 <= page_rect.height * 0.86
                and (
                    any(ch.isdigit() for ch in compact)
                    or re.search(r"[{}\[\]|\\/]", compact)
                    or (len(compact) >= 4 and compact.isupper())
                )
            )
            if diagram_row:
                stats["diagram-row"] += 1
            else:
                merged_kept.append(line)
        kept = merged_kept
    if not kept:
        return "", dict(stats)
    heights = sorted(line.height for line in kept)
    median_height = heights[len(heights) // 2]
    left_positions = sorted(line.rect.x0 for line in kept)
    common_left = left_positions[max(0, int((len(left_positions) - 1) * 0.20))]
    paragraphs: list[str] = []
    current = ""
    previous: LayoutLine | None = None

    for line in kept:
        text = line.text
        title = looks_like_centered_title(line, page_rect, median_height)
        gap = 0.0 if previous is None else line.rect.y0 - previous.rect.y1
        vertical_advance = 0.0 if previous is None else line.rect.y0 - previous.rect.y0
        indent_delta = line.rect.x0 - common_left
        block_changed = previous is not None and line.block_index != previous.block_index
        previous_title = bool(
            previous is not None
            and looks_like_centered_title(previous, page_rect, median_height)
        )
        starts_new = bool(
            current
            and (
                title
                or previous_title
                or gap > max(6.0, median_height * 0.95)
                or (
                    indent_delta > page_rect.width * 0.035
                    and vertical_advance > median_height * 0.55
                )
                or (
                    block_changed
                    and vertical_advance > median_height * 0.70
                    and current[-1:] in SENTENCE_END
                )
            )
        )

        if starts_new:
            normalized = normalize_inline(current)
            if normalized:
                paragraphs.append(normalized)
            current = text
        else:
            current = smart_join(current, text)
        previous = line

    if current.strip():
        paragraphs.append(normalize_inline(current))

    text = "\n\n".join(paragraph for paragraph in paragraphs if paragraph)
    if meaningful_character_count(text) < minimum_characters:
        stats["low-content-page"] += 1
        return "", dict(stats)
    return text, dict(stats)


def read_sidecar(path: Path | None) -> list[str]:
    if path is None or not path.is_file():
        return []
    return path.read_text(encoding="utf-8", errors="replace").split("\f")


def copy_visible_page(
    source_document: pymupdf.Document,
    source_page: pymupdf.Page,
    target_page: pymupdf.Page,
    fallback_dpi: int,
) -> str:
    image_xrefs: set[int] = set()
    inserted = 0
    covered_area = 0.0

    for image_info in source_page.get_images(full=True):
        xref = image_info[0]
        if xref in image_xrefs:
            continue
        image_xrefs.add(xref)
        try:
            rectangles = source_page.get_image_rects(xref)
            extracted = source_document.extract_image(xref)
            stream = extracted.get("image")
            if not stream or not rectangles:
                continue
            for rectangle in rectangles:
                visible_rectangle = rectangle & source_page.rect
                covered_area += max(0.0, visible_rectangle.get_area())
                target_page.insert_image(
                    rectangle,
                    stream=stream,
                    keep_proportion=False,
                    overlay=False,
                )
                inserted += 1
        except Exception:
            continue

    page_area = max(1.0, source_page.rect.get_area())
    if inserted == 0 or covered_area / page_area < 0.85:
        pixmap = source_page.get_pixmap(dpi=fallback_dpi, alpha=False)
        target_page.insert_image(
            target_page.rect,
            stream=pixmap.tobytes("jpeg", jpg_quality=90),
            keep_proportion=False,
            overlay=False,
        )
        return "rasterized"
    return "copied-images"


def choose_font_size(rectangle: pymupdf.Rect, text: str, preferred: float) -> float:
    size = max(1.8, preferred)
    while size > 1.8:
        characters_per_line = max(1.0, rectangle.width / size)
        available_lines = max(1.0, rectangle.height / (size * 1.15))
        estimated_capacity = characters_per_line * available_lines * 0.82
        if len(text) <= estimated_capacity:
            break
        size -= 0.25
    return max(1.8, size)


def insert_reading_layer(
    page: pymupdf.Page,
    text: str,
    preferred_font_size: float,
    font_name: str,
) -> None:
    text = text.strip()
    if not text:
        return

    margin = max(12.0, min(page.rect.width, page.rect.height) * 0.025)
    rectangle = pymupdf.Rect(
        margin,
        margin,
        page.rect.width - margin,
        page.rect.height - margin,
    )
    font_size = choose_font_size(rectangle, text, preferred_font_size)
    result = page.insert_textbox(
        rectangle,
        text,
        fontname=font_name,
        fontsize=font_size,
        lineheight=1.15,
        render_mode=3,
        overlay=True,
    )
    if result < 0:
        raise RuntimeError("The normalized reading text did not fit on the page.")


def parse_page_range(value: str | None, page_count: int) -> tuple[int, int]:
    if not value:
        return 0, page_count
    match = re.fullmatch(r"\s*(\d+)\s*-\s*(\d+)\s*", value)
    if not match:
        raise ValueError("Page range must look like 7-9.")
    start = max(0, int(match.group(1)) - 1)
    end = min(page_count, int(match.group(2)))
    if start >= end:
        raise ValueError("Page range is empty.")
    return start, end


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pdf")
    parser.add_argument("output_pdf")
    parser.add_argument("--sidecar")
    parser.add_argument("--visible-source", help="Optional PDF used only for visible page appearance")
    parser.add_argument("--font-size", type=float, default=3.2)
    parser.add_argument(
        "--font-name",
        default="china-s",
        choices=["china-s", "china-t", "japan", "korea"],
    )
    parser.add_argument("--fallback-dpi", type=int, default=220)
    parser.add_argument("--pages", help="1-based range for testing, for example 7-9")
    parser.add_argument("--text-output")
    parser.add_argument("--prefer-pdf-text", action="store_true")
    parser.add_argument("--scan-layout", action="store_true")
    parser.add_argument("--filter-margins", action="store_true")
    parser.add_argument("--drop-diagram-labels", action="store_true")
    parser.add_argument("--header-ratio", type=float, default=0.10)
    parser.add_argument("--footer-ratio", type=float, default=0.12)
    parser.add_argument("--minimum-readable-characters", type=int, default=6)
    arguments = parser.parse_args()

    input_path = Path(arguments.input_pdf)
    output_path = Path(arguments.output_pdf)
    sidecar_pages = read_sidecar(Path(arguments.sidecar) if arguments.sidecar else None)
    source_document = pymupdf.open(input_path)
    visible_document = pymupdf.open(arguments.visible_source) if arguments.visible_source else source_document
    if len(visible_document) != len(source_document):
        raise ValueError("Visible source and OCR PDF must have the same page count.")
    output_document = pymupdf.open()
    start, end = parse_page_range(arguments.pages, len(source_document))
    normalized_pages: list[str] = []

    all_layout_lines: list[list[LayoutLine]] = []
    page_rects: list[pymupdf.Rect] = []
    repeated_keys: set[str] = set()
    if arguments.scan_layout:
        for page in source_document:
            all_layout_lines.append(extract_layout_lines(page))
            page_rects.append(page.rect)
        if arguments.filter_margins:
            repeated_keys = repeated_margin_keys(
                all_layout_lines,
                page_rects,
                arguments.header_ratio,
                arguments.footer_ratio,
            )
        print(
            f"READING_LAYER_SCAN_ANALYSIS pages={len(source_document)} "
            f"repeated_margin_patterns={len(repeated_keys)}",
            flush=True,
        )

    try:
        for source_index in range(start, end):
            source_page = source_document[source_index]
            visible_page = visible_document[source_index]
            target_page = output_document.new_page(
                width=visible_page.rect.width,
                height=visible_page.rect.height,
            )
            if visible_document is not source_document:
                target_page.show_pdf_page(
                    target_page.rect,
                    visible_document,
                    source_index,
                    keep_proportion=False,
                    overlay=False,
                )
                copy_method = "copied-source-page"
            else:
                copy_method = copy_visible_page(
                    visible_document,
                    visible_page,
                    target_page,
                    arguments.fallback_dpi,
                )

            stats: dict[str, int] = {}
            text = ""
            if arguments.scan_layout:
                text, stats = scan_layout_text(
                    all_layout_lines[source_index],
                    source_page.rect,
                    repeated_keys,
                    arguments.header_ratio,
                    arguments.footer_ratio,
                    arguments.drop_diagram_labels,
                    arguments.minimum_readable_characters,
                )

            if not text:
                raw_text = ""
                if not arguments.prefer_pdf_text and source_index < len(sidecar_pages):
                    raw_text = sidecar_pages[source_index]
                text = normalize_page_text(raw_text)
            if not text:
                text = extract_page_text(source_page)

            insert_reading_layer(
                target_page,
                text,
                arguments.font_size,
                arguments.font_name,
            )
            normalized_pages.append(text)
            dropped = sum(stats.values())
            print(
                f"READING_LAYER {source_index + 1}/{end} "
                f"{copy_method} chars={len(text)} dropped={dropped}",
                flush=True,
            )

        output_document.set_metadata(visible_document.metadata)
        if start == 0 and end == len(source_document):
            table_of_contents = visible_document.get_toc()
            if table_of_contents:
                output_document.set_toc(table_of_contents)
        output_document.save(output_path, garbage=4, deflate=True, clean=True)
    finally:
        output_document.close()
        if visible_document is not source_document:
            visible_document.close()
        source_document.close()

    if arguments.text_output:
        Path(arguments.text_output).write_text(
            "\n\n\f\n\n".join(normalized_pages),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"READING_LAYER_ERROR {error}", file=sys.stderr, flush=True)
        raise
