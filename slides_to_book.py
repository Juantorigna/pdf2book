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
# pdfminer's stand-in for a glyph it can't map to Unicode (e.g. a bracket
# piece from an Office-inserted equation's symbol font). Always a sign the
# "text" is actually a rendered math/graphic fragment, never real prose.
CID_PLACEHOLDER_RE = re.compile(r"\(cid:\d+\)")

# A Beamer/PowerPoint cover slide (title, authors, affiliation, date) carries
# an affiliation line essentially no genuine content slide does. Only ever
# checked against a source PDF's first page, so it can't misfire on a later
# slide that happens to mention a university in passing.
TITLE_SLIDE_AFFILIATION_RE = re.compile(r"\b(?:department|university|college|institute)\s+of\b", re.IGNORECASE)

# Default word-boundary tolerance, as a fraction of the preceding character's
# font size (pdfplumber's x_tolerance_ratio). Many slide-deck PDFs don't
# encode a literal space glyph between words, so pdfplumber has to infer word
# breaks purely from the horizontal gap between characters; a fixed-size gap
# (pdfplumber's absolute-point default) is too coarse across the range of
# font sizes a slide mixes (titles vs. body), so words at body size can end
# up glued together while larger titles happen to still split correctly.
DEFAULT_WORD_X_TOLERANCE_RATIO = 0.1

FOOTER_ZONE_RATIO = 0.85  # bottom fraction of the page treated as footer territory

SUBSCRIPT_SIZE_RATIO = 0.85
# As a fraction of body font size: how much vertical whitespace separates two
# lines before they're treated as visually distinct paragraphs rather than
# the same flowing block. A math-heavy slide's natural single-line leading
# (e.g. an itemized list of definitions, each wrapping across 1-2 lines) can
# run close to 0.5x body size, so too low a ratio splits one coherent block
# into a cluster per line/bullet -- each becomes its own tiny, out-of-context
# rendered image. 0.6 keeps that kind of block together while still
# separating genuinely distinct formulas, which tend to be spaced apart by
# noticeably more (the vertical room LaTeX reserves for stacked notation like
# summations, fractions, and matrices).
DEFAULT_CLUSTER_GAP_RATIO = 0.6
CLUSTER_GAP_MIN = 3.0

RENDER_RESOLUTION = 200  # dpi used when rasterizing math/image regions
CROP_PAD = 4  # points of padding around a cropped region

NON_ALNUM_RE = re.compile(r"[^A-Za-z0-9]+")


def sanitize_filename_component(name):
    return NON_ALNUM_RE.sub("_", name).strip("_") or "doc"


def extract_page_lines(pdf_path, word_x_tolerance_ratio=DEFAULT_WORD_X_TOLERANCE_RATIO):
    """Return a list of pages, each a list of line dicts with text/size/bbox,
    plus a parallel list of each page's embedded raster images."""
    pages = []
    page_images = []
    page_heights = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            words = page.extract_words(
                extra_attrs=["size"], x_tolerance_ratio=word_x_tolerance_ratio
            )
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


def is_title_slide(lines):
    """Heuristic for a Beamer/PowerPoint cover slide (deck title, authors,
    department/university affiliation, date) as opposed to a real content
    slide. Callers only apply this to a source PDF's own first page."""
    return any(TITLE_SLIDE_AFFILIATION_RE.search(line["text"]) for line in lines)


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
    if CID_PLACEHOLDER_RE.search(text):
        return True
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


def cluster_lines(lines, body_size, cluster_gap_ratio=DEFAULT_CLUSTER_GAP_RATIO):
    if not lines:
        return []
    gap_threshold = max(CLUSTER_GAP_MIN, cluster_gap_ratio * body_size)
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

    def __init__(self, pdf_path, image_dir, filename_prefix="", resolution=RENDER_RESOLUTION):
        self.pdf = pdfplumber.open(pdf_path)
        self.image_dir = image_dir
        self.filename_prefix = filename_prefix
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
        filename = f"{self.filename_prefix}p{page_index + 1:03d}_{self._counters[page_index]:02d}.png"
        path = os.path.join(self.image_dir, filename)
        cropped.save(path)
        return path


def build_slide_items(
    lines, images, page_index, renderer, footer_top, cluster_gap_ratio=DEFAULT_CLUSTER_GAP_RATIO
):
    """Return (titles, items) where items is a top-sorted list of
    {'kind': 'bullet', 'text': ...} or {'kind': 'image', 'path': ...}."""
    if not lines and not images:
        return [], []

    if lines:
        # Math/equation fragments (including glyphs pdfminer couldn't map to
        # Unicode, e.g. bracket pieces from an inserted equation object) are
        # excluded from heading detection: such a fragment can carry a
        # spuriously large reported font size and would otherwise hijack the
        # "biggest font on the slide" heuristic, getting misclassified as the
        # title and stripped out of the math cluster it actually belongs to.
        heading_candidates = [line for line in lines if not has_math_symbol(line["text"])]
        heading_size = max(line["size"] for line in (heading_candidates or lines))
        titles = [
            line["text"]
            for line in lines
            if line["size"] == heading_size and not has_math_symbol(line["text"])
        ]
        body_lines = [
            line for line in lines if line["size"] != heading_size or has_math_symbol(line["text"])
        ]
        body_size = dominant_body_size(lines, heading_size)
    else:
        titles, body_lines, body_size = [], [], 0

    items = []
    if renderer is None:
        for line in body_lines:
            items.append({"top": line["top"], "kind": "bullet", "text": line["text"]})
    else:
        for cluster in cluster_lines(body_lines, body_size, cluster_gap_ratio):
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


def build_slides(pages, page_images, footer_tops, renderer, cluster_gap_ratio=DEFAULT_CLUSTER_GAP_RATIO):
    """Build (titles, items) per slide. When a slide's title(s) exactly match
    the previous slide's, the heading is suppressed (titles becomes []) so the
    repeated title doesn't print again — its content just continues under the
    last-printed heading, until a genuinely new title appears."""
    slides = []
    last_titles = None
    for page_index, lines in enumerate(pages):
        images = page_images[page_index] if renderer is not None else []
        titles, items = build_slide_items(
            lines, images, page_index, renderer, footer_tops[page_index], cluster_gap_ratio
        )
        if not titles and not items:
            continue
        display_titles = [] if titles and titles == last_titles else titles
        if titles:
            last_titles = titles
        slides.append((display_titles, items))
    return slides


def relative_path(path, output_path):
    return os.path.relpath(path, start=os.path.dirname(os.path.abspath(output_path)) or ".")


def write_markdown(docs, output_path, append=False):
    mode = "a" if append and os.path.exists(output_path) else "w"
    with open(output_path, mode, encoding="utf-8") as f:
        if mode == "a":
            f.write("\n---\n\n")
        for doc_heading, slides in docs:
            if doc_heading is not None:
                f.write(f"# {doc_heading}\n\n")
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


def write_docx(docs, output_path, append=False):
    from docx import Document
    from docx.shared import Inches
    from PIL import Image

    max_width_in = 6.0
    if append and os.path.exists(output_path):
        document = Document(output_path)
        document.add_page_break()
    else:
        document = Document()
    for doc_heading, slides in docs:
        if doc_heading is not None:
            document.add_paragraph(doc_heading, style="Heading 1")
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


def process_pdf(
    pdf_path,
    min_ratio,
    image_dir,
    filename_prefix,
    use_images,
    word_x_tolerance_ratio,
    cluster_gap_ratio,
    skip_title_slide,
):
    pages, page_images, page_heights = extract_page_lines(pdf_path, word_x_tolerance_ratio)
    pages, footer_tops = clean_pages(pages, min_ratio, page_heights)

    if skip_title_slide and pages and is_title_slide(pages[0]):
        pages[0] = []
        page_images[0] = []

    renderer = None
    if use_images:
        renderer = ImageRenderer(pdf_path, image_dir, filename_prefix=filename_prefix)

    try:
        return build_slides(pages, page_images, footer_tops, renderer, cluster_gap_ratio)
    finally:
        if renderer is not None:
            renderer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_pdfs",
        nargs="+",
        help="Path(s) to the slide-deck PDF(s). Multiple PDFs are concatenated, in order, into one output",
    )
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
    parser.add_argument(
        "--append",
        action="store_true",
        help="Append to output/--docx files instead of overwriting, if they already exist",
    )
    parser.add_argument(
        "--word-x-tolerance-ratio",
        type=float,
        default=DEFAULT_WORD_X_TOLERANCE_RATIO,
        help=(
            "Word-boundary sensitivity, as a fraction of font size (default: "
            f"{DEFAULT_WORD_X_TOLERANCE_RATIO}). Lower this if extracted text has words "
            "running together with no space; raise it if unrelated words are getting "
            "fused into one bullet."
        ),
    )
    parser.add_argument(
        "--cluster-gap-ratio",
        type=float,
        default=DEFAULT_CLUSTER_GAP_RATIO,
        help=(
            "How much vertical whitespace (as a fraction of body font size) separates "
            f"two lines before a math region is split into its own image (default: "
            f"{DEFAULT_CLUSTER_GAP_RATIO}). Lower this if unrelated formulas are being "
            "merged into one image; raise it if one formula/list is being split across "
            "several images that don't make sense on their own."
        ),
    )
    parser.add_argument(
        "--keep-title-slide",
        action="store_true",
        help=(
            "Keep each source PDF's first slide even when it looks like a cover/title "
            "slide (deck title, authors, department/university affiliation, date). By "
            "default this slide is dropped since it's not lecture content."
        ),
    )
    args = parser.parse_args()

    # A per-source heading disambiguates decks whenever more than one is
    # combined in the book, whether that's several PDFs in this call or one
    # PDF being appended onto a book built from earlier calls.
    multi = len(args.input_pdfs) > 1 or args.append
    image_dir = os.path.splitext(args.output)[0] + "_images"

    docs = []
    seen_stems = Counter()
    for pdf_path in args.input_pdfs:
        stem = os.path.splitext(os.path.basename(pdf_path))[0]
        seen_stems[stem] += 1
        # Disambiguate the same filename passed more than once in this call;
        # a stem-based prefix (rather than a plain positional index) is what
        # keeps image filenames from colliding across separate --append runs.
        unique_stem = stem if seen_stems[stem] == 1 else f"{stem}_{seen_stems[stem]}"
        prefix = f"{sanitize_filename_component(unique_stem)}_" if multi else ""
        slides = process_pdf(
            pdf_path,
            args.min_ratio,
            image_dir,
            prefix,
            not args.no_images,
            args.word_x_tolerance_ratio,
            args.cluster_gap_ratio,
            not args.keep_title_slide,
        )
        docs.append((stem if multi else None, slides))

    docx_path = None
    if args.docx:
        docx_path = args.output
        if docx_path.lower().endswith(".md"):
            docx_path = docx_path[: -len(".md")] + ".docx"
        elif not docx_path.lower().endswith(".docx"):
            docx_path = docx_path + ".docx"

    # If --output was itself given as the .docx path, docx_path and output
    # are the same file: only write the docx, since writing plain-text
    # Markdown into that same path first would destroy it before write_docx
    # gets a chance to open it (in --append mode) or would just leave a
    # bogus non-docx file behind (otherwise).
    same_path = docx_path is not None and os.path.abspath(docx_path) == os.path.abspath(args.output)
    if not same_path:
        write_markdown(docs, args.output, append=args.append)
    if docx_path is not None:
        write_docx(docs, docx_path, append=args.append)


if __name__ == "__main__":
    main()
