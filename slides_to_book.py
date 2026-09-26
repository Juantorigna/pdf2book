#!/usr/bin/env python3
"""Convert a slide-deck PDF into a condensed, book-style Markdown/Word document."""

import argparse
import re
from collections import Counter

import pdfplumber

Y_TOLERANCE = 3.0
PAGE_NUMBER_ONLY_RE = re.compile(r"^\d+\s*/\s*\d+$|^\d+$")
TRAILING_PAGE_NUMBER_RE = re.compile(r"\s*\d+\s*/\s*\d+\s*$|\s*\d+\s*$")


def extract_page_lines(pdf_path):
    """Return a list of pages, each a list of {text, size, top} line dicts."""
    pages = []
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
                size = max(w["size"] for w in group)
                top = min(w["top"] for w in group)
                lines.append({"text": text, "size": size, "top": top})

            pages.append(lines)
    return pages


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


def clean_pages(pages, min_ratio):
    boilerplate = find_boilerplate_keys(pages, min_ratio)

    cleaned = []
    for lines in pages:
        kept = []
        for line in lines:
            text = line["text"]
            if boilerplate_key(text) in boilerplate:
                continue
            if PAGE_NUMBER_ONLY_RE.match(text):
                continue
            kept.append(line)
        cleaned.append(kept)
    return cleaned


def slide_to_title_and_bullets(lines):
    if not lines:
        return [], []

    max_size = max(line["size"] for line in lines)
    titles = [line["text"] for line in lines if line["size"] == max_size]
    bullets = [line["text"] for line in lines if line["size"] != max_size]
    return titles, bullets


def build_slides(pages):
    slides = []
    for lines in pages:
        titles, bullets = slide_to_title_and_bullets(lines)
        if not titles and not bullets:
            continue
        slides.append((titles, bullets))
    return slides


def write_markdown(slides, output_path):
    with open(output_path, "w", encoding="utf-8") as f:
        for titles, bullets in slides:
            for title in titles:
                f.write(f"## {title}\n\n")
            for bullet in bullets:
                f.write(f"- {bullet}\n")
            f.write("\n")


def write_docx(slides, output_path):
    from docx import Document

    document = Document()
    for titles, bullets in slides:
        for title in titles:
            document.add_paragraph(title, style="Heading 2")
        for bullet in bullets:
            document.add_paragraph(bullet, style="List Bullet")
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
    args = parser.parse_args()

    pages = extract_page_lines(args.input_pdf)
    pages = clean_pages(pages, args.min_ratio)
    slides = build_slides(pages)

    write_markdown(slides, args.output)

    if args.docx:
        docx_path = args.output
        if docx_path.lower().endswith(".md"):
            docx_path = docx_path[: -len(".md")] + ".docx"
        elif not docx_path.lower().endswith(".docx"):
            docx_path = docx_path + ".docx"
        write_docx(slides, docx_path)


if __name__ == "__main__":
    main()
