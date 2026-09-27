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
   Word boundaries use a font-size-relative gap (`x_tolerance_ratio`,
   `--word-x-tolerance-ratio` to adjust, default 0.1) rather than a fixed
   point size: many slide PDFs don't encode a literal space glyph between
   words, so pdfplumber infers breaks purely from the horizontal gap
   between characters, and a fixed-size gap is too coarse across the range
   of font sizes one slide mixes (title vs. body) — words at body size end
   up glued together (`AnIntroduction`) while larger titles happen to
   still split correctly on the same fixed threshold.
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
   real content, not a page number. This kind of removal never sets where
   the image-crop footer boundary sits (see step 6) — only the recurring
   per-page footer/boilerplate line does. A page-number-only match is a
   single bare digit with no recurring-text confirmation behind it, so on
   a slide whose body text runs close to the bottom margin, a math
   subscript (the `0` in a trailing `x_0`) can land in the footer zone and
   be mistaken for one; letting that set the crop boundary would clip the
   rendered image right through the slide's real last line instead of
   just keeping it out of the actual footer.
5. Title detection: on each page, the line(s) at the page's max font size
   become the heading; everything else is body content. A line is never a
   heading candidate, and never counted toward the max-size search, if it
   carries a math signal (see step 6) or simply trails off with
   sentence-continuation punctuation (`.`, `:`, `,`, `;`) — a real slide
   title is a short label and is never phrased that way, but an
   explanatory sentence introducing a formula ("...is given by:") often
   is. Either way, the exclusion matters because an inline reference like
   an inserted equation object's bracket glyphs, or even a bare `(x, y)` /
   `(0, 1)` coordinate pair with no recognizable math symbol at all, can
   report a spuriously large nominal font size — without this exclusion
   such a fragment gets misclassified as the slide's title, either
   stripping it out of the math cluster/sentence it actually belongs to
   (so the rendered image or bullet ends up missing the piece that was
   misread as a heading) or burying the real formula-introducing sentence
   inside a garbled, wrongly-styled heading instead of a normal bullet.
6. Math/diagram fidelity: PDF math (fractions, matrices, sub/superscripts)
   is a 2D arrangement of glyphs, not linear text — extracting it as text
   and reading top-to-bottom produces nonsense. So each slide's remaining
   lines are clustered into visual paragraphs (by vertical gap — lines
   closer together than `--cluster-gap-ratio` × body font size, default
   0.6, stay in the same paragraph/image; a wider gap starts a new one),
   and any cluster containing a math signal (a non-ASCII math/Greek
   symbol, an isolated operator token, an off-size sub/superscript line,
   or a glyph pdfminer couldn't map to Unicode — rendered as a literal
   `(cid:NN)` placeholder, typically a piece of an inserted equation
   object's symbol font) is rasterized straight from the PDF page and
   embedded as an image instead of being emitted as text. The 0.6 default
   is tuned so a math-heavy itemized list (each bullet its own short
   paragraph, wrapped across 1-2 lines with tight leading) renders as one
   coherent image instead of being sliced into one disconnected fragment
   per line/bullet, while formulas that are genuinely distinct (the
   larger vertical gaps LaTeX reserves around a summation, fraction, or
   stacked matrix) still land in separate images. Embedded raster images already in the PDF
   (plots, diagrams, logos) are extracted and placed the same way,
   positioned by vertical order among the surrounding bullets. Plain prose
   stays as real, flowing text. Pass `--no-images` to disable this and get
   old-style plain-text-only extraction.
7. Output: Markdown (`## title` + `- bullet` per line, `![](...)` for
   rendered images, saved to a `<output>_images/` folder next to the
   output file). Optional `--docx` flag also writes a Word file using
   `Heading 2` + `List Bullet` styles, with images embedded inline.

Each source PDF's first slide is checked against a title-slide heuristic
(a department/university affiliation line — `Department of ...`,
`University of ...` — that a genuine content slide essentially never has)
and dropped by default if it matches: it's the deck's cover slide (title,
authors, affiliation, date), not lecture content, so it doesn't belong in
a book of notes. Pass `--keep-title-slide` to keep it. Only ever checked
against page one, so a later slide that happens to mention a university
in passing is never at risk.

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
python slides_to_book.py input.pdf output.md --word-x-tolerance-ratio 0.05
python slides_to_book.py input.pdf output.md --cluster-gap-ratio 0.8
python slides_to_book.py input.pdf output.md --keep-title-slide

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
  as a title. The math-signal and trailing-punctuation exclusions catch
  the inline-equation-fragment case, but a non-math, non-punctuated short
  body fragment that happens to render at the same inflated size as the
  page's real title (rare, but not impossible) would still slip through.
- Word-boundary detection is still a geometric heuristic (gap-vs-font-size),
  not a real space-character check, because many source PDFs don't encode
  one. A deck with unusually tight justified body text can still need a
  lower `--word-x-tolerance-ratio` than the default to fully separate
  words; conversely, an unusually wide-tracked or monospaced font could
  need a higher one if unrelated words start fusing into one bullet.
- Multi-column slide layouts, and lines whose fragments overlap almost
  the same vertical position, can interleave text out of true reading
  order — grouping is purely by vertical position, not layout analysis.
- Math-region detection is heuristic (symbol/size/operator based). It can
  occasionally sweep a short plain-text line into a rendered image (mildly
  wasteful, not incorrect) or, rarer, miss a math line that uses no
  special symbols and matches the body font size.
- Clustering is a single global gap threshold per page, not layout-aware.
  A deck with much looser or tighter line spacing than typical Beamer/
  PowerPoint output may need `--cluster-gap-ratio` adjusted to keep a
  multi-line formula/list together (raise it) or stop unrelated formulas
  from merging into one image (lower it).
- Boilerplate detection matches after stripping a trailing page number,
  but fuzzy differences elsewhere in a footer (e.g. a changing date) still
  won't be caught.
- Rendered images are cropped from a rasterized page (200 dpi default),
  not vector-extracted, so they're raster PNGs even when the source was
  vector art.
- Title-slide detection is a single keyword heuristic (a department/
  university affiliation line) checked only on each source's first page.
  A cover slide without that phrasing (e.g. title/authors/date but no
  institution line) won't be recognized and will pass through unless
  removed by hand; a genuine first content slide that happens to name an
  institution would be wrongly dropped (use `--keep-title-slide`).

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
