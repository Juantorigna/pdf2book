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
4. Page-number-only lines (`3`, `3/20`) are stripped via regex, but only
   inside the bottom ~15% of the page — a bare digit is also how Beamer
   renders `enumerate` list markers in the middle of a slide, and those are
   real content, not a page number.
5. Title detection: on each page, the line(s) at the page's max font size
   become the heading; everything else is body content.
6. Math/diagram fidelity: PDF math (fractions, matrices, sub/superscripts)
   is a 2D arrangement of glyphs, not linear text — extracting it as text
   and reading top-to-bottom produces nonsense. So each slide's remaining
   lines are clustered into visual paragraphs (by vertical gap), and any
   cluster containing a math signal (a non-ASCII math/Greek symbol, an
   isolated operator token, or an off-size sub/superscript line) is
   rasterized straight from the PDF page and embedded as an image instead
   of being emitted as text. Embedded raster images already in the PDF
   (plots, diagrams, logos) are extracted and placed the same way,
   positioned by vertical order among the surrounding bullets. Plain prose
   stays as real, flowing text. Pass `--no-images` to disable this and get
   old-style plain-text-only extraction.
7. Output: Markdown (`## title` + `- bullet` per line, `![](...)` for
   rendered images, saved to a `<output>_images/` folder next to the
   output file). Optional `--docx` flag also writes a Word file using
   `Heading 2` + `List Bullet` styles, with images embedded inline.

## Dependencies

- `pdfplumber` (required) — also pulls in `pypdfium2` and `Pillow`, used
  for rasterizing pages/crops.
- `python-docx` (only for `--docx` output)

## Usage

```bash
python slides_to_book.py input.pdf output.md
python slides_to_book.py input.pdf output.md --docx
python slides_to_book.py input.pdf output.md --min-ratio 0.4
python slides_to_book.py input.pdf output.md --no-images

# multiple PDFs are concatenated, in order, into one output
python slides_to_book.py lesson1.pdf lesson2.pdf lesson3.pdf book.md --docx

# add a new pack of slides onto an already-existing output, instead of
# overwriting it (works with output.md, an existing output.docx, or both)
python slides_to_book.py lesson4.pdf book.md --docx --append
python slides_to_book.py lesson4.pdf lesson5.pdf MyExistingNotes.docx --docx --append
```

Each source PDF is processed independently (its own boilerplate/footer
stripping, its own title-repetition state), so unrelated decks don't bleed
into each other. A per-source `# <filename>` heading is added whenever more
than one deck ends up in the same output — either because multiple PDFs
were given in one call, or because `--append` is adding to a book that
already has earlier content. `--append` adds a `---` separator in
Markdown / a page break in Word before the new content; if the target
file doesn't exist yet, `--append` just creates it normally.

## Known limitations

- Title detection assumes one font size clearly dominates per slide.
  Decks with uniform font sizes throughout will misclassify everything
  as a title.
- Multi-column slide layouts, and lines whose fragments overlap almost
  the same vertical position, can interleave text out of true reading
  order — grouping is purely by vertical position, not layout analysis.
- Math-region detection is heuristic (symbol/size/operator based). It can
  occasionally sweep a short plain-text line into a rendered image (mildly
  wasteful, not incorrect) or, rarer, miss a math line that uses no
  special symbols and matches the body font size.
- Boilerplate detection matches after stripping a trailing page number,
  but fuzzy differences elsewhere in a footer (e.g. a changing date) still
  won't be caught.
- Rendered images are cropped from a rasterized page (200 dpi default),
  not vector-extracted, so they're raster PNGs even when the source was
  vector art.

## Possible next steps

- Detect and preserve nested bullet levels (currently flattened to one
  list level).
- Fuzzy-match near-duplicate boilerplate lines beyond a trailing page
  number (e.g. footers with a changing date).
- Reading-order reconstruction for multi-column slides (cluster by x0
  ranges before grouping by top position).
- Directory input (glob a folder of PDFs) instead of listing each file —
  multi-file concatenation itself is already supported.
- Configurable render resolution / image width for `--docx` output.
