# slides-to-book

## Purpose

Convert slide-deck PDFs (lecture slides, exported presentations) into a
condensed, book-style document that flows as normal A4 text instead of one
slide per page. Strips repeated boilerplate (university/course name,
footers, page numbers) automatically, so the result reads like proper
notes rather than a slide printout.

## Current state

Single script: `slides_to_book.py`. No packaging, no tests yet.

Pipeline:
1. `pdfplumber` extracts words per page, each with font size and position.
2. Words within ~3pt of vertical position are grouped into lines.
3. Boilerplate removal: any line whose exact text repeats on ≥50% of pages
   (`--min-ratio` to adjust) is dropped from every page. Catches uni name,
   course code, recurring footers. Matching is done after stripping a
   trailing page-number token (`3`, `3/20`, ...) from the end of the line,
   so a footer that differs only by an embedded slide number is still
   caught.
4. Page-number-only lines (`3`, `3/20`) are stripped via regex.
5. Title detection: on each page, the line(s) at the page's max font size
   become the heading; everything smaller becomes bullet body text.
6. Output: Markdown (`## title` + `- bullet` per slide). Optional `--docx`
   flag also writes a Word file using `Heading 2` + `List Bullet` styles.

## Dependencies

- `pdfplumber` (required)
- `python-docx` (only for `--docx` output)

## Usage

```bash
python slides_to_book.py input.pdf output.md
python slides_to_book.py input.pdf output.md --docx
python slides_to_book.py input.pdf output.md --min-ratio 0.4
```

## Known limitations

- Title detection assumes one font size clearly dominates per slide.
  Decks with uniform font sizes throughout will misclassify everything
  as a title.
- Multi-column slide layouts can interleave lines out of order — grouping
  is purely by vertical position, not reading order.
- Text layer only. Diagrams, charts, and images are ignored entirely.
- Boilerplate detection matches after stripping a trailing page number,
  but fuzzy differences elsewhere in a footer (e.g. a changing date) still
  won't be caught.

## Possible next steps

- Detect and preserve nested bullet levels (currently flattened to one
  list level).
- Fuzzy-match near-duplicate boilerplate lines beyond a trailing page
  number (e.g. footers with a changing date).
- Reading-order reconstruction for multi-column slides (cluster by x0
  ranges before grouping by top position).
- Optional image passthrough: extract embedded raster images
  (`pdfimages`/PyMuPDF) and reinsert them near their slide's heading.
- CLI batch mode: process a directory of PDFs into one merged book.
