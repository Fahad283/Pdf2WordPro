"""Bounded page alignment, visual diagnostics, and raster scoring."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import mean

import cv2
import numpy as np
from PIL import Image
import pymupdf

from .text_metrics import normalize

MAX_SIDE = 850
MAX_BLOCKS = 100


@dataclass
class PageProfile:
    text: str
    words: Counter
    width: float
    height: float


def profile(page: pymupdf.Page, page_text: str | None = None) -> PageProfile:
    text = page.get_text("text") if page_text is None else page_text
    words = Counter(normalize(text[:24_000]).split())
    return PageProfile(text, words, page.rect.width, page.rect.height)


def _dice(left: Counter, right: Counter) -> float | None:
    total = left.total() + right.total()
    return 2 * (left & right).total() / total if total else None


def _dimension_score(left: PageProfile, right: PageProfile) -> float:
    return mean((min(left.width, right.width) / max(left.width, right.width),
                 min(left.height, right.height) / max(left.height, right.height)))


def match_pages(source: list[PageProfile], rendered: list[PageProfile]) -> tuple[dict[int, int], list[int]]:
    """Align in display order, with gaps for deleted or inserted pages."""
    n, m = len(source), len(rendered)
    gap = .25
    previous = [-gap * index for index in range(m + 1)]
    steps = bytearray((n + 1) * (m + 1))
    for i, original in enumerate(source, 1):
        current = [-gap * i]
        for j, output in enumerate(rendered, 1):
            lexical = _dice(original.words, output.words)
            geometry = _dimension_score(original, output)
            position = 1 - abs((i - 1) / max(1, n - 1) - (j - 1) / max(1, m - 1))
            confidence = (
                .78 * lexical + .15 * geometry + .07 * position if lexical is not None
                else .62 * geometry + .12 * position
            )
            choices = (
                previous[j - 1] + confidence - .39,
                previous[j] - gap,
                current[j - 1] - gap,
            )
            transition = max(range(3), key=choices.__getitem__)
            current.append(choices[transition])
            steps[i * (m + 1) + j] = transition
        previous = current
    pairs = {}
    extras = []
    i, j = n, m
    while i or j:
        transition = steps[i * (m + 1) + j]
        if not i or (j and transition == 2):
            extras.append(j - 1)
            j -= 1
        elif not j or transition == 1:
            i -= 1
        else:
            pairs[i - 1] = j - 1
            i -= 1
            j -= 1
    return pairs, sorted(extras)


def _canvas(page: pymupdf.Page, zoom: float, size: tuple[int, int]) -> np.ndarray:
    raster = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), colorspace=pymupdf.csRGB, alpha=False)
    pixels = np.frombuffer(raster.samples, dtype=np.uint8).reshape(raster.height, raster.width, 3)
    width, height = size
    canvas = np.full((height, width, 3), 255, dtype=np.uint8)
    rows, cols = min(height, raster.height), min(width, raster.width)
    canvas[:rows, :cols] = pixels[:rows, :cols]
    return canvas


def ssim(first: np.ndarray, second: np.ndarray, *, content_mask: np.ndarray | None = None) -> float:
    """Gaussian-window SSIM with constants from the original formulation."""
    first, second = first.astype(np.float32), second.astype(np.float32)
    first_mean = cv2.GaussianBlur(first, (11, 11), 1.5)
    second_mean = cv2.GaussianBlur(second, (11, 11), 1.5)
    first_variance = np.maximum(0, cv2.GaussianBlur(first * first, (11, 11), 1.5) - first_mean ** 2)
    second_variance = np.maximum(0, cv2.GaussianBlur(second * second, (11, 11), 1.5) - second_mean ** 2)
    covariance = cv2.GaussianBlur(first * second, (11, 11), 1.5) - first_mean * second_mean
    luminance_stabilizer, contrast_stabilizer = (0.01 * 255) ** 2, (0.03 * 255) ** 2
    similarity = (
        (2 * first_mean * second_mean + luminance_stabilizer) * (2 * covariance + contrast_stabilizer)
        / ((first_mean ** 2 + second_mean ** 2 + luminance_stabilizer)
           * (first_variance + second_variance + contrast_stabilizer))
    )
    selected = similarity if content_mask is None or not np.any(content_mask) else similarity[content_mask]
    return float(np.clip(selected.mean(), -1.0, 1.0))


def _as_bbox(box: list | tuple, width: float, height: float) -> list[float]:
    limits = (width, height, width, height)
    return [round(min(1., max(0., float(value) / extent)), 5) for value, extent in zip(box, limits)]


def _page_box(box: list | tuple, page: pymupdf.Page) -> list[float]:
    rect = pymupdf.Rect(box) * page.rotation_matrix
    return _as_bbox(list(rect), page.rect.width, page.rect.height)


def _iou(first: list, second: list) -> float:
    left, top = max(first[0], second[0]), max(first[1], second[1])
    right, bottom = min(first[2], second[2]), min(first[3], second[3])
    overlap = max(0, right - left) * max(0, bottom - top)
    first_area = (first[2] - first[0]) * (first[3] - first[1])
    second_area = (second[2] - second[0]) * (second[3] - second[1])
    total = first_area + second_area - overlap
    return overlap / total if total > 0 else 0.0


def _blocks(page: pymupdf.Page, authored: dict | None = None) -> list[dict]:
    if authored and authored.get("blocks"):
        return [
            {
                "text": str(block["text"])[:500],
                "bbox": _as_bbox(block["bbox"], page.rect.width, page.rect.height),
            }
            for block in authored["blocks"][:MAX_BLOCKS]
            if block.get("text") and len(block.get("bbox", [])) == 4
        ]
    raw = page.get_text("blocks")
    return [
        {"text": item[4][:500], "bbox": _page_box(item[:4], page)}
        for item in raw if item[6] == 0 and normalize(item[4])
    ][:MAX_BLOCKS]


def _match_blocks(source: list[dict], result: list[dict]) -> tuple[float | None, dict]:
    if not source:
        return None, {"source_blocks": 0, "output_blocks": len(result)}
    original_tokens = [Counter(normalize(item["text"]).split()) for item in source]
    converted_tokens = [Counter(normalize(item["text"]).split()) for item in result]
    candidates = []
    for i, source_item in enumerate(source):
        for j, output_item in enumerate(result):
            lexical = _dice(original_tokens[i], converted_tokens[j]) or 0.
            if lexical >= .28:
                iou = _iou(source_item["bbox"], output_item["bbox"])
                candidates.append((.7 * lexical + .3 * iou, i, j, iou))
    matched = {}
    taken = set()
    for _, i, j, overlap in sorted(candidates, reverse=True):
        if i not in matched and j not in taken:
            matched[i] = (j, overlap)
            taken.add(j)
    missed = [item for index, item in enumerate(source) if index not in matched]
    displaced = [
        {"source": source[i], "output_bbox": result[j]["bbox"], "iou": round(overlap, 4)}
        for i, (j, overlap) in matched.items() if overlap < .55
    ]
    score = sum(overlap for _, overlap in matched.values()) / len(source)
    return score, {
        "source_blocks": len(source), "output_blocks": len(result), "matched_blocks": len(matched),
        "missing_blocks": missed[:16], "displaced_blocks": displaced[:16],
    }


def _match_images(source_page: pymupdf.Page, target_page: pymupdf.Page, authored: dict | None) -> tuple[float | None, dict]:
    if authored is not None and "images" in authored:
        expected = [
            _as_bbox(box, source_page.rect.width, source_page.rect.height)
            for box in authored["images"][:MAX_BLOCKS] if isinstance(box, (list, tuple)) and len(box) == 4
        ]
    else:
        expected = [_page_box(info["bbox"], source_page) for info in source_page.get_image_info()[:MAX_BLOCKS]]
    actual = [_page_box(info["bbox"], target_page) for info in target_page.get_image_info()[:MAX_BLOCKS]]
    comparisons = sorted(
        (_iou(original, output), i, j)
        for i, original in enumerate(expected)
        for j, output in enumerate(actual)
    )
    selected = {}
    used = set()
    for overlap, i, j in reversed(comparisons):
        if overlap > .02 and i not in selected and j not in used:
            selected[i] = (j, overlap)
            used.add(j)
    return (sum(overlap for _, overlap in selected.values()) / len(expected) if expected else None), {
        "expected_images": len(expected), "rendered_images": len(actual),
        "missing_images": [box for i, box in enumerate(expected) if i not in selected][:16],
        "displaced_images": [
            {"original_bbox": expected[i], "output_bbox": actual[j], "iou": round(overlap, 4)}
            for i, (j, overlap) in selected.items() if overlap < .55
        ][:16],
    }


def _diff(original: np.ndarray, rendered: np.ndarray, first_gray: np.ndarray, second_gray: np.ndarray) -> np.ndarray:
    distance = np.abs(original.astype(np.int16) - rendered.astype(np.int16)).max(axis=2)
    mask = distance > 23
    result = cv2.cvtColor(np.minimum(first_gray, second_gray), cv2.COLOR_GRAY2RGB)
    result = (result.astype(np.float32) * .36 + 255. * .64).astype(np.uint8)
    result[mask & (first_gray < second_gray)] = (202, 48, 70)
    result[mask & (second_gray < first_gray)] = (35, 100, 200)
    result[mask & (first_gray == second_gray)] = (126, 59, 160)
    return result


def _render_pair(original: pymupdf.Page, output: pymupdf.Page) -> tuple[dict, tuple]:
    width, height = max(original.rect.width, output.rect.width), max(original.rect.height, output.rect.height)
    zoom = MAX_SIDE / max(width, height)
    size = max(1, round(width * zoom)), max(1, round(height * zoom))
    first, second = _canvas(original, zoom, size), _canvas(output, zoom, size)
    first_gray = cv2.cvtColor(first, cv2.COLOR_RGB2GRAY)
    second_gray = cv2.cvtColor(second, cv2.COLOR_RGB2GRAY)
    content = cv2.dilate(((first_gray < 240) | (second_gray < 240)).astype(np.uint8),
                         np.ones((9, 9), np.uint8)).astype(bool)
    structural = ssim(first_gray, second_gray)
    foreground = ssim(first_gray, second_gray, content_mask=content)
    mean_difference = (
        float(np.abs(first.astype(np.int16) - second.astype(np.int16))[content].mean()) / 255
        if np.any(content) else 0.
    )
    return {
        "ssim": round(structural, 6), "foreground_ssim": round(foreground, 6),
        "mean_content_difference": round(mean_difference, 6),
        "source_ink_fraction": round(float((first_gray < 240).mean()), 6),
        "output_ink_fraction": round(float((second_gray < 240).mean()), 6),
    }, (first, second, _diff(first, second, first_gray, second_gray))


def _sample(indexes: list[int], limit: int) -> set[int]:
    count = min(len(indexes), max(0, limit))
    if not count:
        return set()
    if count == 1:
        return {indexes[0]}
    return {indexes[round(position * (len(indexes) - 1) / (count - 1))] for position in range(count)}


def compare_visual(
    source: pymupdf.Document, output: pymupdf.Document, pages: list[dict],
    output_dir: Path, *, max_visual_pages: int,
) -> tuple[dict, list[dict], dict, list[PageProfile]]:
    expected = [profile(page, pages[i].get("text") if i < len(pages) else None) for i, page in enumerate(source)]
    actual = [profile(page) for page in output]
    alignment, extras = match_pages(expected, actual)
    samples = _sample(sorted(alignment), max_visual_pages)
    diagnostics = []
    artifacts = {}
    for i, item in enumerate(expected):
        diagnostic = {
            "source_page": i + 1,
            "expected_dimensions": [round(item.width, 2), round(item.height, 2)],
            "rendered_page": None,
            "warnings": [],
        }
        if i not in alignment:
            diagnostic["warnings"].append("Source page has no corresponding rendered page.")
            diagnostics.append(diagnostic)
            continue
        j = alignment[i]
        original, rendered = source[i], output[j]
        page_truth = pages[i] if i < len(pages) else None
        dimensions = _dimension_score(item, actual[j])
        image_score, image_evidence = _match_images(original, rendered, page_truth)
        diagnostic.update({
            "rendered_page": j + 1, "rendered_dimensions": [round(actual[j].width, 2), round(actual[j].height, 2)],
            "dimension_score": round(dimensions, 6), "token_overlap": _dice(item.words, actual[j].words),
            "image_position_score": None if image_score is None else round(image_score, 6),
            "image_evidence": image_evidence,
        })
        if dimensions < .98:
            diagnostic["warnings"].append("Rendered page size differs from the source.")
        if i in samples:
            block_score, block_evidence = _match_blocks(_blocks(original, page_truth), _blocks(rendered))
            metrics, pictures = _render_pair(original, rendered)
            visual = .58 * max(0, metrics["foreground_ssim"]) + .17 * (1 - metrics["mean_content_difference"])
            visual += .10 * dimensions + .15 * (max(0, metrics["ssim"]) if block_score is None else block_score)
            diagnostic.update(metrics, layout_score=round(visual, 6), block_evidence=block_evidence,
                              block_position_score=None if block_score is None else round(block_score, 6))
            if metrics["source_ink_fraction"] > .005 and metrics["output_ink_fraction"] < .0005:
                diagnostic["warnings"].append("The corresponding rendered page is visually empty.")
                diagnostic["visually_empty"] = True
            if visual < .65:
                diagnostic["warnings"].append("The page has low layout similarity.")
            for kind, array in zip(("original", "rendered", "difference"), pictures):
                label = f"{kind}_{i + 1:03d}"
                filename = f"{label}.png"
                Image.fromarray(array).save(output_dir / filename)
                artifacts[label] = filename
            diagnostic["artifacts"] = {kind: f"{kind}_{i + 1:03d}" for kind in ("original", "rendered", "difference")}
        diagnostics.append(diagnostic)
    scores = [page["layout_score"] for page in diagnostics if "layout_score" in page]
    image_scores = [page["image_position_score"] for page in diagnostics if page.get("image_position_score") is not None]
    complete = sum(page["rendered_page"] is not None and not page.get("visually_empty") for page in diagnostics)
    return {
        "source_pages": len(source), "rendered_pages": len(output),
        "compared_pages": len(scores), "unmatched_rendered_pages": [index + 1 for index in extras],
        "page_completeness": round(complete / len(source), 6),
        "layout_similarity": round(mean(scores), 6) if scores else None,
        "image_position_score": round(mean(image_scores), 6) if image_scores else None,
    }, diagnostics, artifacts, actual
