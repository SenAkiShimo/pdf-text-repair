#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

import pymupdf

CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
COMMON_RE = re.compile(
    r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaffA-Za-z0-9\s"
    r"，。！？；：、（）【】《》〈〉“”‘’…—·,.!?;:'\"()\[\]{}<>/%+*=\\_-]"
)


def sample_indexes(page_count: int, limit: int = 12) -> list[int]:
    if page_count <= limit:
        return list(range(page_count))
    indexes = {0, 1, max(0, page_count - 2), page_count - 1}
    slots = max(1, limit - len(indexes))
    for i in range(slots):
        position = round((i + 1) * (page_count - 1) / (slots + 1))
        indexes.add(max(0, min(page_count - 1, position)))
    return sorted(indexes)[:limit]


def visible_text(text: str) -> str:
    return "".join(ch for ch in text if not ch.isspace())


def suspicious_ratio(text: str) -> float:
    compact = visible_text(text)
    if not compact:
        return 0.0
    suspicious = 0
    for char in compact:
        category = unicodedata.category(char)
        if COMMON_RE.fullmatch(char):
            continue
        if category.startswith("C") or category in {"So", "Co", "Cn"}:
            suspicious += 1
    return suspicious / len(compact)


def image_coverage(page: pymupdf.Page) -> float:
    area = max(1.0, page.rect.width * page.rect.height)
    coverage = 0.0
    try:
        for info in page.get_image_info(xrefs=False):
            bbox = info.get("bbox")
            if bbox and len(bbox) == 4:
                rect = pymupdf.Rect(bbox)
                coverage += max(0.0, rect.width * rect.height)
    except Exception:
        return 0.0
    return min(1.0, coverage / area)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pdf")
    args = parser.parse_args()
    path = Path(args.input_pdf)
    if not path.is_file():
        raise FileNotFoundError(path)

    document = pymupdf.open(path)
    try:
        count = len(document)
        indexes = sample_indexes(count)
        rows = []
        for index in indexes:
            page = document[index]
            text = page.get_text("text") or ""
            compact = visible_text(text)
            chars = len(compact)
            weird = suspicious_ratio(text)
            cjk = len(CJK_RE.findall(compact))
            coverage = image_coverage(page)
            rows.append({
                "page": index + 1,
                "textChars": chars,
                "cjkChars": cjk,
                "suspiciousRatio": round(weird, 4),
                "imageCoverage": round(coverage, 4),
            })

        text_pages = sum(1 for row in rows if row["textChars"] >= 24)
        blank_text_pages = len(rows) - text_pages
        suspicious_pages = sum(
            1 for row in rows
            if row["textChars"] >= 24 and (
                row["suspiciousRatio"] >= 0.055
                or (row["cjkChars"] < 3 and row["textChars"] >= 80 and row["imageCoverage"] >= 0.5)
            )
        )
        image_pages = sum(1 for row in rows if row["imageCoverage"] >= 0.55)
        sample_count = max(1, len(rows))
        no_text_ratio = blank_text_pages / sample_count
        suspicious_text_ratio = suspicious_pages / max(1, text_pages)
        image_ratio = image_pages / sample_count

        if no_text_ratio >= 0.72 and image_ratio >= 0.5:
            mode = "scan"
            confidence = min(0.99, 0.72 + no_text_ratio * 0.22)
            summary = "抽样页面大多没有可提取文字，且以整页图像为主；推荐使用扫描书高精度 OCR。"
        elif suspicious_text_ratio >= 0.35:
            mode = "force"
            confidence = min(0.96, 0.66 + suspicious_text_ratio * 0.28)
            summary = "PDF 有文字层，但抽样文本含较多异常字符；推荐彻底重建乱码文字层。"
        elif 0.18 <= no_text_ratio < 0.72:
            mode = "skip"
            confidence = min(0.92, 0.64 + abs(0.45 - no_text_ratio) * 0.2)
            summary = "部分页面有正常文字，部分页面没有文字；推荐保留正常文字并补识别图片页。"
        elif text_pages >= max(1, math.ceil(sample_count * 0.72)):
            mode = "reading"
            confidence = 0.82 if suspicious_text_ratio < 0.1 else 0.68
            summary = "PDF 已有可提取文字；推荐仅整理为 Readest 连续朗读层，不重新 OCR。"
        else:
            mode = "skip"
            confidence = 0.58
            summary = "文件结构不完全明确；推荐使用保守的混合型 PDF 模式。"

        payload = {
            "pageCount": count,
            "sampledPages": [row["page"] for row in rows],
            "sampleCount": len(rows),
            "pagesWithText": text_pages,
            "pagesWithoutText": blank_text_pages,
            "suspiciousTextPages": suspicious_pages,
            "imageDominantPages": image_pages,
            "recommendedMode": mode,
            "confidence": round(confidence, 3),
            "summary": summary,
            "samples": rows,
        }
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    finally:
        document.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(f"PDF_ANALYZE_ERROR {error}", file=sys.stderr)
        raise
