#!/usr/bin/env python3
"""Extract highlight text from a KFX file using position data from a .yjr JSON file.

This script relies on the KFX Input plugin's `kfxlib` library (included in this
repository) to decode the KFX container. It converts the book into a JSON
structure with content and position information and then maps the annotation
positions directly onto that content.
"""
import json
import sys
from pathlib import Path
from html import escape

# Allow importing kfxlib either from the extracted folder or the bundled zip
base_dir = Path(__file__).parent
extracted = base_dir / "kfxlib_extracted"
if extracted.exists():
    sys.path.insert(0, str(extracted))
else:
    sys.path.insert(0, str(base_dir / "KFX Input.zip"))
from kfxlib import yj_book
from kfxlib.ion import IonSymbol
from kfxlib.yj_container import YJFragment


def load_content_sections(kfx_path):
    """Return sorted list of text sections with position and length."""
    book = yj_book.YJ_Book(kfx_path)
    content_json = json.loads(book.convert_to_json_content().decode("utf-8"))

    sections = [e for e in content_json.get("data", []) if e.get("type") == 1]
    sections.sort(key=lambda x: x["position"])

    # Infer text length from next section's position
    for i, sec in enumerate(sections[:-1]):
        sec["length"] = sections[i + 1]["position"] - sec["position"]
    if sections:
        sections[-1]["length"] = len(sections[-1]["content"])
    return sections


def extract_text(sections, start, end):
    """Extract text between the given start and end positions."""
    parts = []
    # Find the first section that might contain the start position
    idx = 0
    while idx < len(sections) - 1 and sections[idx + 1]["position"] <= start:
        idx += 1

    # Collect text from overlapping sections
    while idx < len(sections) and sections[idx]["position"] < end:
        sec = sections[idx]
        sec_start = sec["position"]
        sec_end = sec_start + sec["length"]
        slice_start = max(start, sec_start)
        slice_end = min(end + 1, sec_end)
        if slice_end > slice_start:
            a = slice_start - sec_start
            b = slice_end - sec_start
            parts.append(sec["content"][a:b])
        idx += 1
    return "".join(parts).replace("\n", " ").strip()


def load_navigation(kfx_path):
    """Return (pages, toc) from the KFX navigation data."""
    book = yj_book.YJ_Book(kfx_path)
    book.decode_book(set_approximate_pages=0)

    nav = book.fragments.get("$389", first=True)
    if nav is None:
        return [], []

    pages = []
    toc_items = []

    pos_info = book.collect_content_position_info()
    eid_to_pid = {}
    for chunk in pos_info:
        if chunk.eid not in eid_to_pid:
            eid_to_pid[chunk.eid] = chunk.pid - chunk.eid_offset

    for container in nav.value[0].get("$392", []):
        if isinstance(container, IonSymbol):
            container = book.fragments.get(ftype="$391", fid=container)
        data = container.value if isinstance(container, YJFragment) else container
        typ = data.get("$235")
        if typ == "$237":  # page list
            page_list = data.get("$247", [])
            for entry in page_list:
                pid = eid_to_pid.get(entry["$246"]["$155"], 0) + entry["$246"].get("$143", 0)
                label = entry["$241"]["$244"]
                pages.append((pid, label))
            pages.sort(key=lambda x: x[0])
        elif typ == "$212":  # toc
            def build_items(items):
                result = []
                for itm in items:
                    eid = itm["$246"]["$155"]
                    offset = itm["$246"].get("$143", 0)
                    pid = eid_to_pid.get(eid, 0) + offset
                    label = itm["$241"]["$244"]
                    node = {
                        "label": label,
                        "pid": pid,
                        "children": build_items(itm.get("$247", [])),
                    }
                    result.append(node)
                return result

            toc_items = build_items(data.get("$247", []))

    return pages, toc_items


def generate_html(title, authors, items, output_path, year=""):
    """Write highlights to an HTML file with simple Kindle Notebook styling."""
    style = """
        <style type="text/css">
            .bodyContainer {
                font-family: Arial, Helvetica, sans-serif;
                text-align: center;
                padding-left: 32px;
                padding-right: 32px;
            }
            .notebookFor {
                font-size: 18px;
                font-weight: 700;
                text-align: center;
                color: rgb(119, 119, 119);
                margin: 24px 0px 0px;
                padding: 0px;
            }
            .bookTitle {
                font-size: 32px;
                font-weight: 700;
                text-align: center;
                color: #333333;
                margin-top: 22px;
                padding: 0px;
            }
            .authors {
                font-size: 13px;
                font-weight: 700;
                text-align: center;
                color: rgb(119, 119, 119);
                margin-top: 22px;
                margin-bottom: 24px;
                padding: 0px;
            }
            .noteHeading {
                font-size: 18px;
                font-weight: 700;
                text-align: left;
                color: #333333;
                margin-top: 20px;
                padding: 0px;
            }
            .sectionHeading {
                font-size: 24px;
                font-weight: 700;
                text-align: left;
                color: #333333;
                margin-top: 24px;
                padding: 0px;
            }
            .highlight_yellow {
                color: rgb(247, 206, 0);
            }
            .noteText {
                font-size: 18px;
                font-weight: 500;
                text-align: left;
                color: #333333;
                margin: 2px 0px 0px;
                padding: 0px;
            }
            hr {
                border: 0px none;
                height: 1px;
                background: none repeat scroll 0% 0% rgb(221, 221, 221);
            }
        </style>
    """

    html_parts = [
        "<?xml version='1.0' encoding='UTF-8' ?>",
        "<!DOCTYPE html PUBLIC '-//W3C//DTD XHTML 1.0 Strict//EN'",
        "  'http://www.w3.org/TR/xhtml1/DTD/xhtml1-strict.dtd'>",
        "<html xmlns='http://www.w3.org/TR/1999/REC-html-in-xml' xml:lang='en' lang='en'>",
        "<head>",
        "<meta charset='UTF-8' />",
        style,
        "<title></title>",
        "</head>",
        "<body>",
        "<div class='bodyContainer'>",
        "<div class='notebookFor'>Notebook for</div>",
        f"<div class='bookTitle'>{escape(title)}</div>",
        f"<div class='authors'>{escape(', '.join(authors))}</div>",
        "<div class='citation'>Citation (APA): {author} ({year}). <i>{t}</i> [Kindle version]. Retrieved from Amazon.com</div>".format(
            author=escape(authors[0]) if authors else "",
            year=escape(year),
            t=escape(title),
        ),
        "<hr />",
    ]

    current_section = None
    for item in items:
        if item.get("section") and item["section"] != current_section:
            html_parts.append(f"<div class='sectionHeading'>{escape(item['section'])}</div>")
            current_section = item["section"]

        meta_parts = []
        if item.get("chapter"):
            meta_parts.append(item["chapter"])
        if item.get("page"):
            meta_parts.append(f"Page {item['page']}")
        meta_str = " - " + " >  ".join(meta_parts) if meta_parts else ""

        text = escape(item.get("text", ""))
        if item.get("type") == "note":
            html_parts.append(f"<div class='noteHeading'>Note{meta_str}</div>")
        elif item.get("type") == "bookmark":
            html_parts.append(f"<div class='noteHeading'>Bookmark{meta_str}</div>")
        else:
            html_parts.append(
                f"<div class='noteHeading'>Highlight (<span class='highlight_yellow'>yellow</span>){meta_str}</div>"
            )
        html_parts.append(f"<div class='noteText'>{text}</div>")

    html_parts.extend(["</div>", "</body>", "</html>"])

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))


def main():
    if len(sys.argv) != 3:
        print("Usage: python extract_highlights_kfxlib.py <annotations.json> <book.kfx>")
        sys.exit(1)

    json_file = sys.argv[1]
    kfx_file = sys.argv[2]

    with open(json_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    ann_obj = data.get("annotation.cache.object", {})
    annotations = ann_obj.get("annotation.personal.highlight", [])
    notes = ann_obj.get("annotation.personal.note", [])
    bookmarks = ann_obj.get("annotation.personal.bookmark", [])
    if not annotations and not notes and not bookmarks:
        print("No highlights, notes, or bookmarks found in annotation data.")
        return

    sections = load_content_sections(kfx_file)
    meta = yj_book.YJ_Book(kfx_file).get_metadata()
    pages, toc = load_navigation(kfx_file)

    def page_for_pid(pid):
        p = None
        for pp, label in pages:
            if pp <= pid:
                p = label
            else:
                break
        return p

    def find_section(pid):
        section = None
        chapter = None
        for sec in toc:
            if sec["pid"] <= pid:
                section = sec
            else:
                break
        if section:
            for ch in section.get("children", []):
                if ch["pid"] <= pid:
                    chapter = ch
                else:
                    break
        return (section["label"] if section else None,
                chapter["label"] if chapter else None)

    highlights = []
    notes_by_end = {}
    for n in notes:
        pos = int(n["startPosition"].split(":")[1])
        notes_by_end.setdefault(pos, []).append(n["note"])

    annotations.sort(key=lambda a: int(a["startPosition"].split(":")[1]))

    # Build items for HTML and a separate timeline for printing (highlights + bookmarks)
    timeline = []

    for ann in annotations:
        start = int(ann["startPosition"].split(":")[1])
        end = int(ann["endPosition"].split(":")[1])
        text = extract_text(sections, start, end)
        page = page_for_pid(start)
        section, chapter = find_section(start)

        highlights.append({
            "creationTime": ann["creationTime"],
            "text": text,
            "page": page,
            "section": section,
            "chapter": chapter,
            "type": "highlight",
        })

        # Add highlight to timeline (use lastModificationTime for ordering)
        timeline.append({
            "type": "highlight",
            "creationTime": ann.get("creationTime", ""),
            "lastModificationTime": ann.get("lastModificationTime", ""),
            "text": text,
            "page": page,
            "section": section,
            "chapter": chapter,
            "start": start,
        })

        for note_text in notes_by_end.get(end, []):
            highlights.append({
                "creationTime": "",
                "text": note_text,
                "page": page,
                "section": section,
                "chapter": chapter,
                "type": "note",
            })

    # Add bookmarks to the timeline
    for bm in bookmarks:
        bm_start = int(bm["startPosition"].split(":")[1])
        page = page_for_pid(bm_start)
        section, chapter = find_section(bm_start)
        timeline.append({
            "type": "bookmark",
            "creationTime": bm.get("creationTime", ""),
            "lastModificationTime": bm.get("lastModificationTime", ""),
            "text": "",  # bookmarks have no text selection
            "page": page,
            "section": section,
            "chapter": chapter,
            "start": bm_start,
        })

    # Sort timeline by lastModificationTime (ISO string sort works), break ties by start position
    timeline.sort(key=lambda x: (x.get("lastModificationTime", ""), x.get("start", -1)))

    # Print interleaved timeline
    if timeline:
        print(f"Timeline (by lastModificationTime):\n{'='*60}")
        h_idx = 0
        for item in timeline:
            if item["type"] == "highlight":
                h_idx += 1
                print(f"\nHighlight #{h_idx}")
                if item.get("lastModificationTime"):
                    print(f"Last Modified: {item['lastModificationTime']}")
                elif item.get("creationTime"):
                    print(f"Created: {item['creationTime']}")
                if item.get("page"):
                    print(f"Page: {item['page']}")
                if item.get("section"):
                    print(f"Section: {item['section']}")
                if item.get("chapter"):
                    print(f"Chapter: {item['chapter']}")
                print(f"Text: {item.get('text','')}\n{'-'*60}")
            else:  # bookmark
                print(f"\nBookmark")
                if item.get("lastModificationTime"):
                    print(f"Last Modified: {item['lastModificationTime']}")
                elif item.get("creationTime"):
                    print(f"Created: {item['creationTime']}")
                if item.get("page"):
                    print(f"Page: {item['page']}")
                if item.get("section"):
                    print(f"Section: {item['section']}")
                if item.get("chapter"):
                    print(f"Chapter: {item['chapter']}")
                print('-'*60)

    output_html = Path(kfx_file).with_suffix(".highlights.html")
    year = ""
    if getattr(meta, "issue_date", None):
        year = str(meta.issue_date).split("-")[0]
    generate_html(meta.title or Path(kfx_file).stem, meta.authors or [], highlights, output_html, year)
    print(f"\nSaved HTML highlights to {output_html}")


if __name__ == "__main__":
    main()
