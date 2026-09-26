#!/usr/bin/env python3
"""Convert a slide-deck PDF into a condensed, book-style Markdown/Word document."""

import argparse
import os
import re
from collections import Counter

import pdfplumber

Y_TOLERANCE = 3.0
PAGE_NUMBER_ONLY_RE = re.compile(r"^\d+\s*/\s*\d+$|^\d+$")
TRAILING_PAGE_NUMBER_RE = re.compile(r"\s*\d+\s*/\s*\d+\s*$|\s*\d+\s*$")

# Punctuation that legitimately shows up in plain prose and should not, by
# itself, mark a line as math (smart quotes, dashes, accents).
SAFE_NON_ASCII = set("’‘“”–—´`")
ISOLATED_OPERATOR_RE = re.compile(r"^[=+\-×÷±≤≥≠<>]$")

FOOTER_ZONE_RATIO = 0.85  # bottom fraction of the page treated as footer territory

SUBSCRIPT_SIZE_RATIO = 0.85
CLUSTER_GAP_RATIO = 0.35
CLUSTER_GAP_MIN = 3.0

RENDER_RESOLUTION = 200  # dpi used when rasterizing math/image regions
CROP_PAD = 4  # points of padding around a cropped region


def extract_page_lines(pdf_path):
    """Return a list of pages, each a list of line dicts with text/size/bbox,
    plus a parallel list of each page's embedded raster images."""
    pages = []
    page_images = []
    page_heights = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(extra_attrs=["size"])
            words.sort(key=lambda w: (w["top"], w["x0"]))

            groups = []
            current, current_top = [], None
            for word in words:
                if current and abs(word["top"] - current_top) > Y_TOLERANCE:
                    groups.append(current)
                    current = []
                current.append(word)
                current_top = current[0]["top"]

            if current:
                groups.append(current)

            lines = []
            for group in groups:
                text = " ".join(w["text"] for w in group)
                lines.append(
                    {
                        "text": text,
                        "size": max(w["size"] for w in group),
                        "top": min(w["top"] for w in group),
                        "bottom": max(w["bottom"] for w in group),
                        "x0": min(w["x0"] for w in group),
                        "x1": max(w["x1"] for w in group),
                    }
                )

            pages.append(lines)
            page_images.append(list(page.images))
            page_heights.append(page.height)
    return pages, page_images, page_heights


def boilerplate_key(text):
    """Normalize a line for repetition matching by dropping a trailing page number."""
    return TRAILING_PAGE_NUMBER_RE.sub("", text).strip()


def find_boilerplate_keys(pages, min_ratio):
    num_pages = len(pages)
    if num_pages == 0:
        return set()

    page_counts = Counter()
    for lines in pages:
        keys_on_page = {boilerplate_key(line["text"]) for line in lines}
        for key in keys_on_page:
            if key:
                page_counts[key] += 1

    threshold = min_ratio * num_pages
    return {key for key, count in page_counts.items() if count >= threshold}


def clean_pages(pages, min_ratio, page_heights):
    """Drop boilerplate and page-number-only lines. Returns cleaned pages plus,
    per page, the top of the highest removed line (a proxy for where a footer
    band starts), used later to keep image crops from bleeding into it.

    Page-number-only stripping is restricted to the bottom footer zone of the
    page: a bare "1" or "2" is also how Beamer renders enumerate-list markers
    in the middle of a slide, and those are real content, not a page number.
    """
    boilerplate = find_boilerplate_keys(pages, min_ratio)

    cleaned = []
    footer_tops = []
    for lines, page_height in zip(pages, page_heights):
        footer_zone_top = FOOTER_ZONE_RATIO * page_height
        kept = []
        removed_tops = []
        for line in lines:
            text = line["text"]
            is_boilerplate = boilerplate_key(text) in boilerplate
            is_page_number = line["top"] >= footer_zone_top and PAGE_NUMBER_ONLY_RE.match(text)
            if is_boilerplate or is_page_number:
                removed_tops.append(line["top"])
                continue
            kept.append(line)
        cleaned.append(kept)
        footer_tops.append(min(removed_tops) if removed_tops else None)
    return cleaned, footer_tops


def has_math_symbol(text):
    if any((not ch.isascii()) and ch not in SAFE_NON_ASCII for ch in text):
        return True
    return any(ISOLATED_OPERATOR_RE.match(tok) for tok in text.split())


def dominant_body_size(lines, heading_size):
    body_lines = [line for line in lines if line["size"] != heading_size]
    if not body_lines:
        return heading_size
    sizes = Counter(round(line["size"], 1) for line in body_lines)
    return sizes.most_common(1)[0][0]


def is_math_line(line, body_size):
    if has_math_symbol(line["text"]):
        return True
    return line["size"] < body_size * SUBSCRIPT_SIZE_RATIO


def cluster_lines(lines, body_size):
    if not lines:
        return []
    gap_threshold = max(CLUSTER_GAP_MIN, CLUSTER_GAP_RATIO * body_size)
    clusters = [[lines[0]]]
    for line in lines[1:]:
        if line["top"] - clusters[-1][-1]["bottom"] > gap_threshold:
            clusters.append([line])
        else:
            clusters[-1].append(line)
    return clusters


def cluster_bbox(cluster):
    return {
        "x0": min(line["x0"] for line in cluster),
        "x1": max(line["x1"] for line in cluster),
        "top": min(line["top"] for line in cluster),
        "bottom": max(line["bottom"] for line in cluster),
    }


class ImageRenderer:
    """Lazily rasterizes pages and saves padded crops as PNG files."""

    def __init__(self, pdf_path, image_dir, resolution=RENDER_RESOLUTION):
        self.pdf = pdfplumber.open(pdf_path)
        self.image_dir = image_dir
        self.resolution = resolution
        self.scale = resolution / 72
        self._page_images = {}
        self._counters = Counter()

    def close(self):
        self.pdf.close()

    def _rendered_page(self, page_index):
        if page_index not in self._page_images:
            page = self.pdf.pages[page_index]
            self._page_images[page_index] = page.to_image(resolution=self.resolution).original
        return self._page_images[page_index]

    def crop(self, page_index, bbox, footer_top=None):
        page = self.pdf.pages[page_index]
        x0 = max(bbox["x0"] - CROP_PAD, 0)
        top = max(bbox["top"] - CROP_PAD, 0)
        x1 = min(bbox["x1"] + CROP_PAD, page.width)
        bottom = min(bbox["bottom"] + CROP_PAD, page.height)
        if footer_top is not None:
            bottom = max(min(bottom, footer_top - 1), top + 1)

        rendered = self._rendered_page(page_index)
        box = (x0 * self.scale, top * self.scale, x1 * self.scale, bottom * self.scale)
        cropped = rendered.crop(box)

        os.makedirs(self.image_dir, exist_ok=True)
        self._counters[page_index] += 1
        filename = f"p{page_index + 1:03d}_{self._counters[page_index]:02d}.png"
        path = os.path.join(self.image_dir, filename)
        cropped.save(path)
        return path


def build_slide_items(lines, images, page_index, renderer, footer_top):
    """Return (titles, items) where items is a top-sorted list of
    {'kind': 'bullet', 'text': ...} or {'kind': 'image', 'path': ...}."""
    if not lines and not images:
        return [], []

    if lines:
        heading_size = max(line["size"] for line in lines)
        titles = [line["text"] for line in lines if line["size"] == heading_size]
        body_lines = [line for line in lines if line["size"] != heading_size]
        body_size = dominant_body_size(lines, heading_size)
    else:
        titles, body_lines, body_size = [], [], 0

    items = []
    if renderer is None:
        for line in body_lines:
            items.append({"top": line["top"], "kind": "bullet", "text": line["text"]})
    else:
        for cluster in cluster_lines(body_lines, body_size):
            if any(is_math_line(line, body_size) for line in cluster):
                bbox = cluster_bbox(cluster)
                path = renderer.crop(page_index, bbox, footer_top)
                items.append({"top": bbox["top"], "kind": "image", "path": path})
            else:
                for line in cluster:
                    items.append({"top": line["top"], "kind": "bullet", "text": line["text"]})

        for image in images:
            path = renderer.crop(page_index, image, footer_top)
            items.append({"top": image["top"], "kind": "image", "path": path})

    items.sort(key=lambda item: item["top"])
    return titles, items


def build_slides(pages, page_images, footer_tops, renderer):
    """Build (titles, items) per slide. When a slide's title(s) exactly match
    the previous slide's, the heading is suppressed (titles becomes []) so the
    repeated title doesn't print again — its content just continues under the
    last-printed heading, until a genuinely new title appears."""
    slides = []
    last_titles = None
    for page_index, lines in enumerate(pages):
        images = page_images[page_index] if renderer is not None else []
        titles, items = build_slide_items(lines, images, page_index, renderer, footer_tops[page_index])
        if not titles and not items:
            continue
        display_titles = [] if titles and titles == last_titles else titles
        if titles:
            last_titles = titles
        slides.append((display_titles, items))
    return slides


def relative_path(path, output_path):
    return os.path.relpath(path, start=os.path.dirname(os.path.abspath(output_path)) or ".")


def write_markdown(slides, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        for titles, items in slides:
            for title in titles:
                f.write(f"## {title}\n\n")
            for item in items:
                if item["kind"] == "bullet":
                    f.write(f"- {item['text']}\n")
                else:
                    rel = relative_path(item["path"], output_path)
                    f.write(f"\n![]({rel})\n\n")
            f.write("\n")


def write_docx(slides, output_path):
    from docx import Document
    from docx.shared import Inches
    from PIL import Image

    max_width_in = 6.0
    document = Document()
    for titles, items in slides:
        for title in titles:
            document.add_paragraph(title, style="Heading 2")
        for item in items:
            if item["kind"] == "bullet":
                document.add_paragraph(item["text"], style="List Bullet")
            else:
                with Image.open(item["path"]) as im:
                    width_in = im.width / RENDER_RESOLUTION
                document.add_picture(item["path"], width=Inches(min(width_in, max_width_in)))
    document.save(output_path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdf", help="Path to the slide-deck PDF")
    parser.add_argument("output", help="Path to the output Markdown (or .docx) file")
    parser.add_argument(
        "--docx",
        action="store_true",
        help="Also write a Word document (same base name as output, .docx)",
    )
    parser.add_argument(
        "--min-ratio",
        type=float,
        default=0.5,
        help="Fraction of pages a line must repeat on to be treated as boilerplate (default: 0.5)",
    )
    parser.add_argument(
        "--no-images",
        action="store_true",
        help="Skip rasterizing math regions and embedded images; output plain extracted text only",
    )
    args = parser.parse_args()

    pages, page_images, page_heights = extract_page_lines(args.input_pdf)
    pages, footer_tops = clean_pages(pages, args.min_ratio, page_heights)

    renderer = None
    if not args.no_images:
        image_dir = os.path.splitext(args.output)[0] + "_images"
        renderer = ImageRenderer(args.input_pdf, image_dir)

    try:
        slides = build_slides(pages, page_images, footer_tops, renderer)
        write_markdown(slides, args.output)

        if args.docx:
            docx_path = args.output
            if docx_path.lower().endswith(".md"):
                docx_path = docx_path[: -len(".md")] + ".docx"
            elif not docx_path.lower().endswith(".docx"):
                docx_path = docx_path + ".docx"
            write_docx(slides, docx_path)
    finally:
        if renderer is not None:
            renderer.close()


if __name__ == "__main__":
    main()
