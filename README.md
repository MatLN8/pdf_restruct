# 📄 PDF Extractor

Extract hierarchical section headings and content from well-structured technical PDF documents (standards, specifications, scientific papers). This repository provides a rule-based Python script (`pdf_restruct.py`) that parses numeric section headings (e.g. `4`, `4.2`, `4.2.1`) and exports the content to JSON.

## 🚀 Why rule-based?

For well-structured technical documents, deterministic rule-based extraction is often more reliable, auditable and faster than LLM-based approaches. This script focuses on robust heuristics for numeric sectioning and works offline with no external API calls.

## ✅ Features

- 🔢 Extracts numbered headings (multi-level) and their content.
- 🔗 Skips link spans (avoids false positives on hyperlinks).
- 🧩 Handles headings split across PDF spans or lines (concatenates spans/lines when needed).
- 📚 Uses bookmarks/TOC (if present) to help validate headings.
- 📄 Page-range extraction (`start_page`, `end_page`).
- 🧹 Optional header/footer removal by content or by bounding-box height.
- 🗂️ Outputs flat or nested JSON reflecting section hierarchy.

## ⚠️ Limitations

- Targeted at well-structured documents using numeric sectioning (e.g., standards, specs). Documents with inconsistent numbering, heavy OCR errors, or arbitrary heading formats may not extract correctly.
- Some headings may be split across blocks in complex layouts (multi-column, sidebars); extra tuning may be required.
- Heuristics may need tuning (font-size thresholds, header/footer heights) per document.
- LLMs can complement this tool for fuzzy semantic extraction, but they introduce non-determinism and cost.

## ⚙️ Installation

Requires Python 3.8+ and PyMuPDF (fitz).

Install the dependency with:

```bash
pip install pymupdf
```

## 🧭 Quick Start

Run the extraction script directly. The CLI mirrors the function arguments of `extract_hierarchy_checked` and supports nested or flat JSON output.

Basic example:

```bash
python pdf_restruct.py /path/to/document.pdf --start_page 15 --end_page 34 --start_header_number 4 --output output.json
```

Nested output (preserve hierarchy):

```bash
python pdf_restruct.py /path/to/document.pdf --nested --output nested.json
```

## 🛠️ Important CLI options

- `pdf_path` (positional): Path to the PDF file.
- `--heading_regex`: Regex to detect headings (default matches numeric headings like `1`, `1.2`, `1.2.3`).
- `--min_font_size`: Minimum font size to consider a heading; if not provided (default), font-size filter is disabled.
- `--remove_header_footer_if_contains`: One or more strings; blocks containing any will be ignored (e.g., `Licensed`, `IEC 2015`).
- `--header_height` / `--footer_height`: Numeric thresholds (page points) to ignore blocks near top/bottom of page.
- `--start_page` / `--end_page`: Page range (1-based inclusive).
- `--start_header_number`: Start extracting only after finding this heading number (e.g., `4` or `4.1`).
- `--output`: Output file path. If omitted, defaults to `<pdf_basename>.json` (or `_nested.json` when `--nested`).
- `--nested`: Output nested JSON (hierarchical) instead of flat list.

## 📦 Output format

- Flat: list of objects with keys: `title`, `number`, `level`, `page`, `content`.
- Nested: tree where each node has the same keys plus `children` (list of child sections).

## 🔍 Extending & Tuning

- Adjust `--heading_regex` if your documents use different heading formats.
- Set `--min_font_size` to ignore small artifacts or in-document cross-references.
- Use `--header_height` and `--footer_height` (page coordinates) to remove running headers/footers.

If you hit a PDF that the script fails on, please open an issue and (when possible) attach a small anonymized sample. The project will investigate and integrate additional heuristics only when they target well-structured technical PDF documents (typically standards and specifications).

## 🧪 When to use an LLM

Use this rule-based tool first for deterministic structure extraction. If a document is poorly formatted, contains semantic headings not captured by numeric rules, or you need higher-level interpretation (summaries, inference), use an LLM as a secondary step on the extracted sections.

If you prefer an end-to-end LLM-centered pipeline for structured extraction from PDFs, consider the open-source [`langextract`](https://github.com/google/langextract) project as an alternative. [`langextract`](https://github.com/google/langextract) provides tools and workflows that combine LLMs with parsing logic to extract structured information from PDFs; it's a good option when deterministic heuristics cannot reliably recover document structure.



