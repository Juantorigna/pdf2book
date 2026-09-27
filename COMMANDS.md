# slides_to_book.py — command reference

General shape of every command:

```bash
python slides_to_book.py <input1.pdf> [input2.pdf ...] <output.md> [flags]
```

- One or more PDF paths come first.
- The **last** argument is always the output path.
- Flags can go anywhere after that.

---

## Basic conversion

```bash
python slides_to_book.py Lesson_1.pdf Lesson_1.md
```
Converts one PDF into one Markdown file. Math/diagrams are rendered as
images automatically; a `Lesson_1_images/` folder is created next to the
output to hold them.

## Also produce a Word file

```bash
python slides_to_book.py Lesson_1.pdf Lesson_1.md --docx
```
Writes both `Lesson_1.md` and `Lesson_1.docx` (same name, `.docx`
extension swapped in), with images embedded inline in the Word file.

## Point straight at a `.docx` (no Markdown file wanted)

```bash
python slides_to_book.py Lesson_1.pdf Lesson_1.docx --docx
```
If the output path you give already ends in `.docx`, only that Word file
is written — no separate `.md` is created alongside it.

## Multiple PDFs into one output

```bash
python slides_to_book.py Lesson_1.pdf Lesson_2.pdf Lesson_3.pdf book.md --docx
```
Concatenates all the PDFs, in the order listed, into one book. Each
source gets its own boilerplate/footer cleanup, and (since there's more
than one) a `# <filename>` heading marks where each one starts.

## Add to an existing output later (`--append`)

```bash
python slides_to_book.py Lesson_4.pdf book.md --docx --append
```
Adds the new PDF's content **after** what's already in `book.md` /
`book.docx`, instead of overwriting them. Use this to grow a book over
time as new lecture packs arrive. If the target file doesn't exist yet,
`--append` just creates it normally (nothing to append to).

Works the same way pointing straight at an existing Word file:
```bash
python slides_to_book.py Lesson_4.pdf MyExistingNotes.docx --docx --append
```

**Important:** close the file in Word before running an `--append`
command against it — Windows locks open files, and the script will fail
with `PermissionError: Permission denied` if it can't write to it.

## Adjust boilerplate detection sensitivity

```bash
python slides_to_book.py Lesson_1.pdf Lesson_1.md --min-ratio 0.4
```
A line (footer, course name, etc.) is stripped if it repeats on at least
this fraction of pages. Default is `0.5` (50%). Lower it if repeated
boilerplate is slipping through; raise it if real content is being
stripped by mistake.

## Adjust word-boundary sensitivity

```bash
python slides_to_book.py Lesson_1.pdf Lesson_1.md --word-x-tolerance-ratio 0.05
```
Controls how big a horizontal gap between characters counts as a word
break, as a fraction of font size. Default is `0.1`. Lower it if extracted
text has words running together with no space (`AnIntroduction`); raise
it if unrelated words are getting fused into one bullet.

## Adjust how much math content gets grouped into one image

```bash
python slides_to_book.py Lesson_1.pdf Lesson_1.md --cluster-gap-ratio 0.8
```
Controls how much vertical whitespace (as a fraction of body font size)
separates two lines before a math region is split into its own image.
Default is `0.6`. Raise it if one formula or itemized list of definitions
is being split across several images that don't make sense on their own;
lower it if unrelated formulas are being merged into one image.

## Skip image rendering (plain text only)

```bash
python slides_to_book.py Lesson_1.pdf Lesson_1.md --no-images
```
Falls back to the old plain-text-only extraction: no images are
rendered or embedded, math comes out as best-effort (often garbled)
text, and no `_images/` folder is created. Mainly useful for a quick,
fast pass or a text-only deck with no real math/diagrams.

---

## All flags at a glance

| Flag | Meaning |
|---|---|
| `--docx` | Also write a Word (`.docx`) version |
| `--min-ratio <0-1>` | Repetition threshold for boilerplate stripping (default `0.5`) |
| `--no-images` | Disable math/image rendering; plain text only |
| `--word-x-tolerance-ratio <n>` | Word-boundary sensitivity, as a fraction of font size (default `0.1`) |
| `--cluster-gap-ratio <n>` | How much math content gets grouped into one image, as a fraction of font size (default `0.6`) |
| `--append` | Add to existing output files instead of overwriting them |

---

## Setup reminder

```bash
pip install -r requirements.txt
```
Installs `pdfplumber` and `python-docx` (and their own dependencies,
which include the image-rendering libraries used for `--docx` and math
rendering).
