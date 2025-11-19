"""
restruct_pdf.py — Extract numbered headings and section content from PDFs.

Scans a PDF with PyMuPDF (fitz) and extracts numbered headings (e.g. "1", "1.2", "2.3.4")
together with the text belonging to each section. The script offers heuristics to
concatenate multi-span/multi-line headings, ignore headers/footers, filter by font size,
and validate headings against the document's Table of Contents when available.

Features:
- Configurable heading detection via regex (default matches common numbered headings).
- Optional minimum font-size threshold for heading detection.
- Skip blocks containing specified header/footer markers or within top/bottom margins.
- Limit processing to a page range and optionally start extraction from a specific heading number.
- Uses embedded TOC (if present) to improve heading validation.
- CLI output as flat list or nested hierarchy (JSON).

Output format:
A list of section dicts with keys:
- "number": heading number string (e.g. "4.1")
- "title": cleaned heading title string
- "level": integer depth (number of components in number)
- "page": 1-based page where heading was found
- "content": accumulated text for the section

Dependencies:
- PyMuPDF (pip install pymupdf)

Example CLI:
python restruct_pdf.py doc.pdf --start_page 10 --end_page 50 --remove_header_footer_if_contains "Licensed" --nested --output sections.json
"""


import fitz
import json
import os
import re


def nest_sections_by_hierarchy(sections):
    """
    Takes a flat list of section dicts (with 'number', 'level', etc.) and nests them by hierarchy.
    Returns a tree of nested dicts.
    """
    if not sections:
        return []

    root = []
    stack = []

    for section in sections:
        node = dict(section)
        node['children'] = []
        # Find where to insert
        while stack and stack[-1]['level'] >= node['level']:
            stack.pop()
        if stack:
            stack[-1]['children'].append(node)
        else:
            root.append(node)
        stack.append(node)
    return root


def parse_numbering(num_str):
    """Convert '1.2.3' in [1,2,3]"""
    return [int(x) for x in num_str.split('.')]


def is_next_heading(prev, current):
    """
    Verify if `current` logically follow `prev`.
    Ex : 1.1 → 1.2 ✅ | 1.1 → 2 ✅ | 1.1 → 1.3 ✅ | 1.1 → 1.1 ❌
    """
    if not prev:
        return True

    prev_nums = parse_numbering(prev)
    curr_nums = parse_numbering(current)

    # Même longueur → dernier chiffre +1
    if len(prev_nums) == len(curr_nums):
        return curr_nums[:-1] == prev_nums[:-1] and curr_nums[-1] == prev_nums[-1] + 1

    # Niveau supérieur → redémarrage (ex: 1.3 → 2)
    if len(curr_nums) == 1 and curr_nums[0] == prev_nums[0] + 1:
        return True

    # Passage à un niveau inférieur/plus détaillé (ex: 1 → 1.1 ou 1.2 → 1.2.1)
    if len(curr_nums) == len(prev_nums) + 1 and curr_nums[:-1] == prev_nums:
        return True

    # Passage à un niveau supérieur (ex: 4.1.6 -> 4.2)
    if len(curr_nums) < len(prev_nums):
        # Check if the prefix matches and the last number increments
        if curr_nums[:-1] == prev_nums[:len(curr_nums)-1] and curr_nums[-1] == prev_nums[len(curr_nums)-1] + 1:
            return True

    return False


def extract_hierarchy_checked(
    pdf_path,
    heading_regex=r'^\s*(\d+(?:\.\d+)*)(?:\s+|\.?\s+)?(.*)$',
    min_font_size=None,
    remove_header_footer_if_contains=None,
    header_height=None,
    footer_height=None,
    start_page=None,
    end_page=None,
    start_header_number=None
):
    """
    Extracts a hierarchical structure of headings and their associated content from a PDF file.

    This function scans the specified PDF for headings matching a given regular expression, 
    optionally within a specified page range, and with options to filter out headers/footers 
    and restrict extraction to headings above a minimum font size. It can also leverage the 
    document's Table of Contents (TOC) if available to improve heading detection.

    Parameters:
        pdf_path (str): 
            Path to the PDF file to process.
        heading_regex (str, optional): 
            Regular expression pattern to identify headings. 
            Default matches numbered headings (e.g., "1", "1.2", "2.3.4").
        min_font_size (float, optional): 
            Minimum font size for a text span to be considered a heading.
        remove_header_footer_if_contains (list[str], optional): 
            List of strings or regex patterns; if any are found in a block, 
            that block is skipped (useful for removing headers/footers).
        header_height (float, optional): 
            Height in points from the top of the page to consider as header area. 
            Text blocks within this area are ignored.
        footer_height (float, optional): 
            Height in points from the bottom of the page to consider as footer area. 
            Text blocks within this area are ignored.
        start_page (int, optional): 
            1-based index of the first page to process (inclusive).
        end_page (int, optional): 
            1-based index of the last page to process (inclusive).
        start_header_number (str, optional): 
            If set, extraction starts only when a heading with this number is found.

    Returns:
        list[dict]: 
            A list of sections, each represented as a dictionary with the following keys:
                - "title": The heading title (str).
                - "number": The heading number (str).
                - "level": The heading level (int, based on number of dots in the heading number).
                - "page": The 1-based page number where the heading was found (int).
                - "content": The text content belonging to this section (str).

    Notes:
        - If the PDF contains a Table of Contents (TOC), it is used to improve heading detection.
        - The function attempts to concatenate multi-line or multi-span headings.
        - Non-continuous or out-of-order headings are ignored or treated as references.
        - Content between headings is accumulated as the section's content.
    """
    doc = fitz.open(pdf_path)
    sections = []
    current_section = None
    last_number = None
    started = start_header_number is None

    total_pages = len(doc)
    page_start = start_page - 1 if start_page is not None else 0
    page_end = end_page if end_page is not None else total_pages

    # first ry to find a TOC
    toc = doc.get_toc()  # Returns a list: [ [level, title, page, ...], ... ]
    titles = []
    if len(toc) > 0:
        print(f"Found {len(toc)} TOC entries:")
        for entry in toc:
            level, title, page = entry[:3]
            print(f"Level {level}: {title} (Page {page})")
            titles.append(title)

    for page_num in range(page_start, page_end):
        page = doc[page_num]
        page_height = page.rect.height
        blocks = page.get_text("dict")["blocks"]
        links = page.get_links()
        for _, block in enumerate(blocks):
            if block["type"] != 0:  # Only process text blocks
                continue
            if "lines" not in block:
                continue
            if remove_header_footer_if_contains:
                block_text = " ".join(span["text"] for line in block.get(
                    "lines", []) for span in line["spans"])
                if re.search(r"|".join(remove_header_footer_if_contains), block_text):
                    continue

            y0, y1 = block["bbox"][1], block["bbox"][3]
            if header_height is not None:
                if y0 < header_height:
                    continue
            if footer_height is not None:
                if y1 > page_height - footer_height:
                    continue

            lines = block["lines"]
            line_count = len(lines)
            line_idx = 0
            while line_idx < line_count:
                spans = lines[line_idx]["spans"]
                span_idx = 0
                while span_idx < len(spans):
                    text = spans[span_idx]["text"]
                    font_size = spans[span_idx]["size"]

                    if not text:
                        span_idx += 1
                        continue

                    match = re.match(heading_regex, text)
                    if match and (min_font_size is None or font_size >= min_font_size):
                        num_str = match.group(1)

                        # Skip links
                        span_bbox = fitz.Rect(spans[span_idx]["bbox"])
                        is_link = any(fitz.Rect(link["from"]).intersects(
                            span_bbox) for link in links)
                        if is_link:
                            span_idx += 1
                            continue

                        title = match.group(2) if len(
                            match.groups()) > 1 else ""

                        # Concatenate all following spans in the same line for the title
                        if span_idx + 1 < len(spans):
                            title_parts = [title] if title else []
                            for j in range(span_idx + 1, len(spans)):
                                next_text = spans[j]["text"]
                                if next_text:
                                    title_parts.append(next_text)
                            if title_parts:
                                title = "".join(title_parts)
                                text = text + "".join(title_parts)
                        # If still missing, try next line or block as before
                        if not title or len(title) < 2:
                            # Try next line in same block
                            # Concatenate all following spans in the same line for the title
                            if line_idx + 1 < line_count:
                                next_line_spans = lines[line_idx + 1]["spans"]
                                title_parts = []
                                for span in next_line_spans:
                                    next_text = span["text"]
                                    if next_text:
                                        title_parts.append(next_text)
                                if title_parts:
                                    title = title + \
                                        "".join(title_parts) if title else "".join(
                                            title_parts)
                                    text = text + "".join(title_parts)
                            # Try next block
                            # elif block_idx + 1 < block_count:
                            #     next_block = blocks[block_idx + 1]
                            #     if "lines" in next_block and next_block["lines"]:
                            #         next_block_line = next_block["lines"][0]
                            #         if next_block_line["spans"]:
                            #             next_text = next_block_line["spans"][0]["text"]
                            #             title = title + " " + next_text if title else next_text
                            #             text = text + " " + next_text

                        if not started:
                            if num_str == start_header_number:
                                started = True
                            else:
                                span_idx += 1
                                continue

                        # if there is a TOC, check if the title is in it
                        if len(titles) > 0:
                            if any(num_str in item for item in titles) and is_next_heading(last_number, num_str):
                                if current_section:
                                    sections.append(current_section)

                                current_section = {
                                    "title": " ".join(title.split()),
                                    "number": num_str,
                                    "level": len(num_str.split('.')),
                                    "page": page_num + 1,
                                    "content": ""
                                }
                                last_number = num_str
                            else:
                                if current_section:
                                    current_section["content"] += text
                        elif is_next_heading(last_number, num_str):
                            if current_section:
                                sections.append(current_section)

                            current_section = {
                                "title": " ".join(title.split()),
                                "number": num_str,
                                "level": len(num_str.split('.')),
                                "page": page_num + 1,
                                "content": ""
                            }
                            last_number = num_str
                        else:
                            # Si la numérotation n’est pas cohérente, on l'ignore (référence probable)
                            if current_section:
                                current_section["content"] += text

                    elif current_section and started:
                        current_section["content"] += text
                    span_idx += 1
                if current_section:
                    current_section["content"] += '\n'
                line_idx += 1

    if current_section:
        sections.append(current_section)

    return sections


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Extract PDF hierarchy as JSON.")
    parser.add_argument("pdf_path", help="Path to the PDF file")
    parser.add_argument(
        "--heading_regex", default=r'^\s*(\d+(?:\.\d+)*)(?:\s+|\.?\s+)?(.*)$', help="Regex for headings")
    parser.add_argument("--min_font_size", type=float,
                        default=None, help="Minimum font size for headings (default: None, disables filter)")
    parser.add_argument("--remove_header_footer_if_contains", nargs="*", default=None,
                        help="List of strings; blocks containing any will be ignored")
    parser.add_argument("--header_height", type=float, default=None,
                        help="Header height in points to ignore (y0 < header_height)")
    parser.add_argument("--footer_height", type=float, default=None,
                        help="Footer height in points to ignore (y1 > page_height - footer_height)")
    parser.add_argument("--start_page", type=int, default=None,
                        help="Start page (1-based, inclusive)")
    parser.add_argument("--end_page", type=int, default=None,
                        help="End page (1-based, inclusive)")
    parser.add_argument("--start_header_number", default=None,
                        help="Header number to start extraction from")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    parser.add_argument("--nested", action="store_true",
                        help="Output nested JSON (default: flat)")

    args = parser.parse_args()

    sections = extract_hierarchy_checked(
        pdf_path=args.pdf_path,
        heading_regex=args.heading_regex,
        min_font_size=args.min_font_size,
        remove_header_footer_if_contains=args.remove_header_footer_if_contains,
        header_height=args.header_height,
        footer_height=args.footer_height,
        start_page=args.start_page,
        end_page=args.end_page,
        start_header_number=args.start_header_number
    )

    if args.nested:
        output_data = nest_sections_by_hierarchy(sections)
    else:
        output_data = sections

    output_path = args.output or (os.path.splitext(args.pdf_path)[
                                  0] + ("_nested.json" if args.nested else ".json"))
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    for s in sections:
        indent = "  " * (s["level"] - 1)
        print(f"{indent}🔹 {s['number']} {s['title']} (Page {s['page']})")
