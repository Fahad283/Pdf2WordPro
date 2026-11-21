"""Independent checks for a benchmark DOCX package and its editable content."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
import posixpath
import re
from urllib.parse import unquote, urlsplit
from zipfile import BadZipFile, ZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from lxml import etree

from app.engines import EngineError
from app.engines.pdf_tools import validate_docx

WORD = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
CONTENT_TYPES = "http://schemas.openxmlformats.org/package/2006/content-types"
DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/main"
VML = "urn:schemas-microsoft-com:vml"
MAX_XML_BYTES = 20 * 1024 * 1024
MAX_TABLE_CELLS = 20_000
UNSAFE_FIELD = re.compile(
    r"^\s*(?:DDEAUTO|DDE|INCLUDETEXT|INCLUDEPICTURE|LINK|DATABASE|IMPORT|MACROBUTTON)\b", re.I,
)
SVG_URL = re.compile(r"url\(([^)]*)\)", re.I)
STORY = re.compile(r"word/(?:document|header[^/]*|footer[^/]*|footnotes|endnotes)\.xml\Z")


@dataclass
class EditableContent:
    body: list[str] = field(default_factory=list)
    headers: list[str] = field(default_factory=list)
    footers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)
    fonts: Counter = field(default_factory=Counter)
    sizes: Counter = field(default_factory=Counter)
    sections: list[dict] = field(default_factory=list)
    links: list[dict] = field(default_factory=list)


def _w(name: str) -> str:
    return f"{{{WORD}}}{name}"


def _xml(package: ZipFile, name: str):
    if package.getinfo(name).file_size > MAX_XML_BYTES:
        raise EngineError("An XML part exceeds the DOCX benchmark size limit.")
    with package.open(name) as stream:
        tree = etree.parse(stream, parser=etree.XMLParser(
            resolve_entities=False, load_dtd=False, no_network=True,
        ))
    if tree.docinfo.doctype:
        raise EngineError("The DOCX uses a prohibited XML document type.")
    return tree.getroot()


def _relationship_owner(name: str, members: set[str]) -> str:
    if name == "_rels/.rels":
        return ""
    path = PurePosixPath(name)
    if path.parent.name != "_rels" or path.name == ".rels":
        raise EngineError("The DOCX contains a misplaced relationship part.")
    owner = (path.parent.parent / path.name.removesuffix(".rels")).as_posix()
    if owner not in members:
        raise EngineError("The DOCX contains relationships for a missing package part.")
    return owner


def _internal_target(owner: str, target: str) -> str:
    address = urlsplit(target)
    path = unquote(address.path)
    if address.scheme or address.netloc or address.query or "\\" in path or "\0" in path:
        raise EngineError("The DOCX contains an invalid internal relationship target.")
    if not path and address.fragment and owner:
        return owner
    resolved = posixpath.normpath(path.lstrip("/") if path.startswith("/") else posixpath.join(
        posixpath.dirname(owner), path,
    ))
    if resolved in ("", ".", "..") or resolved.startswith("../"):
        raise EngineError("A DOCX relationship points outside the package.")
    return resolved


def _relationships(package: ZipFile, members: set[str]) -> dict[str, dict[str, dict]]:
    relationships = {}
    for part in sorted(name for name in members if name.endswith(".rels")):
        owner = _relationship_owner(part, members)
        root = _xml(package, part)
        if root.tag != f"{{{PACKAGE_REL}}}Relationships":
            raise EngineError("A DOCX relationship file has an invalid root element.")
        resolved = {}
        for relation in root:
            if relation.tag != f"{{{PACKAGE_REL}}}Relationship":
                continue
            identifier, target, kind = (relation.get(attribute) for attribute in ("Id", "Target", "Type"))
            if not identifier or not target or not kind or identifier in resolved:
                raise EngineError("The DOCX contains an invalid or duplicate relationship.")
            mode = relation.get("TargetMode", "Internal").casefold()
            if mode not in {"internal", "external"}:
                raise EngineError("A DOCX relationship has an invalid target mode.")
            is_external = mode == "external"
            if not is_external:
                target = _internal_target(owner, target)
                if target not in members:
                    raise EngineError("A DOCX relationship references a missing part.")
            resolved[identifier] = {"target": target, "type": kind, "external": is_external}
        relationships[owner] = resolved
    if not any(
        relation["type"].endswith("/officeDocument")
        and relation["target"] == "word/document.xml"
        and not relation["external"]
        for relation in relationships.get("", {}).values()
    ):
        raise EngineError("The DOCX has no package relationship to its main document.")
    return relationships


def _content_types(package: ZipFile, members: set[str]) -> None:
    root = _xml(package, "[Content_Types].xml")
    defaults, overrides = {}, {}
    if root.tag != f"{{{CONTENT_TYPES}}}Types":
        raise EngineError("The DOCX content type manifest is invalid.")
    for child in root:
        content_type = child.get("ContentType", "")
        if not content_type or "macroenabled" in content_type.casefold() or "vba" in content_type.casefold():
            raise EngineError("The DOCX contains an unsupported content type.")
        if child.tag.endswith("}Default"):
            extension = child.get("Extension", "").casefold()
            if not extension or extension in defaults:
                raise EngineError("The DOCX has an invalid or duplicated default content type.")
            defaults[extension] = content_type
        elif child.tag.endswith("}Override"):
            part = child.get("PartName", "").lstrip("/")
            if not part or part in overrides or part not in members:
                raise EngineError("The DOCX has an invalid or duplicated part content type.")
            overrides[part] = content_type
    expected = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
    if overrides.get("word/document.xml") != expected:
        raise EngineError("The package is not a standard Word DOCX document.")
    for name in members - {"[Content_Types].xml"}:
        extension = name.rsplit(".", 1)[-1].casefold() if "." in name else ""
        if name not in overrides and extension not in defaults:
            raise EngineError("A DOCX package part has no registered content type.")


def _paragraph_text(paragraph) -> str:
    text = []
    for node in paragraph.iter(_w("t"), _w("tab"), _w("br"), _w("cr"), _w("noBreakHyphen"), _w("softHyphen")):
        if next(node.iterancestors(_w("p")), None) is not paragraph:
            continue
        if next(node.iterancestors(_w("del")), None) is not None:
            continue
        if node.tag == _w("t"):
            text.append(node.text or "")
        elif node.tag == _w("tab"):
            text.append("\t")
        elif node.tag in {_w("br"), _w("cr")}:
            text.append("\n")
        elif node.tag == _w("noBreakHyphen"):
            text.append("\u2011")
        else:
            text.append("\u00ad")
    return "".join(text)


def _toggled(node) -> bool:
    return node is not None and node.get(_w("val"), "true").casefold() not in {"0", "off", "false"}


def _table_grid(table) -> list[list[str]]:
    return [
        [
            "\n".join(_paragraph_text(p) for p in cell.iter(_w("p")) if (
                next(p.iterancestors(_w("tbl")), None) is table
            ))
            for cell in row.findall(_w("tc"))
        ]
        for row in table.findall(_w("tr"))
    ]


def _field_instructions(root):
    fields: list[list[str] | None] = []
    for node in root.iter(_w("fldChar"), _w("instrText"), _w("fldSimple")):
        if node.tag == _w("fldSimple"):
            yield node.get(_w("instr"), "")
        elif node.tag == _w("instrText"):
            if fields and fields[-1] is not None:
                fields[-1].append(node.text or "")
            elif not fields:
                yield node.text or ""
        else:
            kind = node.get(_w("fldCharType"))
            if kind == "begin":
                fields.append([])
            elif fields and kind in {"separate", "end"}:
                chunks = fields.pop()
                if chunks:
                    yield "".join(chunks)
                if kind == "separate":
                    fields.append(None)
    for chunks in fields:
        if chunks:
            yield "".join(chunks)


def _read_story(root, name: str, relationships: dict[str, dict], output: EditableContent) -> None:
    if name.startswith("word/header"):
        destination = output.headers
        output.counts["headers"] += 1
    elif name.startswith("word/footer"):
        destination = output.footers
        output.counts["footers"] += 1
    elif name in ("word/footnotes.xml", "word/endnotes.xml"):
        destination = output.notes
        note_tag = _w("footnote" if "footnote" in name else "endnote")
        output.counts["footnotes"] += sum(
            item.get(_w("type"), "normal") == "normal" for item in root.findall(note_tag)
        )
    else:
        destination = output.body

    for instruction in _field_instructions(root):
        if UNSAFE_FIELD.search(instruction):
            raise EngineError("The DOCX contains an unsupported external or active field.")
        if re.match(r"^\s*PAGE\b", instruction, flags=re.I):
            output.counts["page_numbers"] += 1
    if root.find(f".//{_w('altChunk')}") is not None or root.find(f".//{_w('object')}") is not None:
        raise EngineError("The DOCX contains an unsupported embedded document.")

    for paragraph in root.iter(_w("p")):
        text = _paragraph_text(paragraph)
        if text:
            destination.append(text)
            output.counts["paragraphs"] += 1
            if next(paragraph.iterancestors(_w("tbl")), None) is None and destination is output.body:
                output.counts["body_paragraphs"] += 1
        style = paragraph.find(f"{_w('pPr')}/{_w('pStyle')}")
        if style is not None:
            identifier = style.get(_w("val"), "").casefold()
            output.counts["styled_paragraphs"] += 1
            if identifier.startswith(("heading", "title")):
                output.counts["headings"] += 1
            if identifier.startswith("list"):
                output.counts["list_styles"] += 1
        numbering = paragraph.find(f"{_w('pPr')}/{_w('numPr')}")
        output.counts["lists"] += int(numbering is not None or (style is not None and identifier.startswith("list")))
        bidi = paragraph.find(f"{_w('pPr')}/{_w('bidi')}")
        if _toggled(bidi):
            output.counts["rtl"] += 1
        for run in paragraph.iterchildren(_w("r")):
            if _toggled(run.find(f"{_w('rPr')}/{_w('rtl')}")):
                output.counts["rtl_runs"] += 1

    table_cells = 0
    for table in root.iter(_w("tbl")):
        grid = _table_grid(table)
        table_cells += sum(map(len, grid))
        if table_cells > MAX_TABLE_CELLS:
            raise EngineError("The document contains too many table cells for benchmark inspection.")
        if grid and destination is output.body:
            output.tables.append(grid)
    for node in root.iter(_w("hyperlink")):
        relation = relationships.get(node.get(f"{{{REL}}}id"), {})
        output.counts["hyperlinks"] += 1
        if len(output.links) < 100:
            output.links.append({
                "text": "".join(child.text or "" for child in node.iter(_w("t")))[:300],
                "target": (relation.get("target") or node.get(_w("anchor")) or "")[:600],
            })
    for paragraph in root.iter(_w("rPr")):
        fonts = paragraph.find(_w("rFonts"))
        if fonts is not None:
            font = fonts.get(_w("ascii")) or fonts.get(_w("hAnsi")) or fonts.get(_w("cs"))
            if font:
                output.fonts[font[:120]] += 1
        size = paragraph.find(_w("sz"))
        if size is not None and (value := size.get(_w("val"), "")).isdigit() and len(value) <= 5:
            output.sizes[str(int(value) / 2)] += 1
        output.counts["bold_runs"] += int(_toggled(paragraph.find(_w("b"))))
        output.counts["italic_runs"] += int(_toggled(paragraph.find(_w("i"))))

    for section in root.iter(_w("sectPr")):
        size = section.find(_w("pgSz"))
        dimensions = {}
        if size is not None:
            width, height = size.get(_w("w"), ""), size.get(_w("h"), "")
            if width.isdecimal() and height.isdecimal() and len(width) < 8 and len(height) < 8:
                dimensions = {"width": int(width) / 20, "height": int(height) / 20}
        output.sections.append(dimensions)
    for node in root.iter(_w("br")):
        output.counts["page_breaks"] += int(node.get(_w("type")) == "page")
    output.counts["page_breaks"] += sum(_toggled(node) for node in root.iter(_w("pageBreakBefore")))


def _check_svg(root) -> None:
    for node in root.iter():
        if not isinstance(node.tag, str):
            continue
        tag = node.tag.rsplit("}", 1)[-1].casefold()
        if tag in {"script", "foreignobject"}:
            raise EngineError("The DOCX contains an active SVG resource.")
        if tag == "style":
            css = node.text or ""
            if "@import" in css.casefold() or any(
                not value.strip(" '\"\t\r\n").startswith("#") for value in SVG_URL.findall(css)
            ):
                raise EngineError("The DOCX contains an unsupported linked SVG style.")
        for key, value in node.attrib.items():
            attribute = key.rsplit("}", 1)[-1].casefold()
            if attribute.startswith("on") or (
                attribute in {"src", "href"} and value and not value.startswith("#")
            ) or any(not url.strip(" '\"\t\r\n").startswith("#") for url in SVG_URL.findall(value)):
                raise EngineError("The DOCX contains an unsupported linked SVG resource.")


def inspect_docx(path: Path) -> EditableContent:
    """Validate archive members and relationships before any rendering."""
    validate_docx(path)
    output = EditableContent()
    try:
        with ZipFile(path) as package:
            members = {item.filename for item in package.infolist() if not item.is_dir()}
            _content_types(package, members)
            all_relationships = _relationships(package, members)
            part_sizes = {item.filename: item.file_size for item in package.infolist()}
            for name in sorted(members):
                if not name.endswith((".xml", ".svg")):
                    continue
                root = _xml(package, name)
                if name.endswith(".svg"):
                    _check_svg(root)
                    continue
                if name == "word/document.xml" and (
                    root.tag != _w("document") or root.find(_w("body")) is None
                ):
                    raise EngineError("The DOCX main document has an invalid Word XML structure.")
                rels = all_relationships.get(name, {})
                for node in root.iter():
                    for identifier in (node.get(f"{{{REL}}}{attribute}") for attribute in ("id", "embed", "link")):
                        if identifier and identifier not in rels:
                            raise EngineError("A DOCX XML part references an undefined relationship.")
                    if node.tag not in (f"{{{DRAWING}}}blip", f"{{{VML}}}imagedata"):
                        continue
                    identifier = node.get(f"{{{REL}}}embed") or node.get(f"{{{REL}}}id")
                    relation = rels.get(identifier, {})
                    if not relation.get("type", "").endswith("/image") or relation.get("external"):
                        raise EngineError("A DOCX drawing has no valid embedded image relationship.")
                    if not part_sizes.get(relation["target"]):
                        raise EngineError("A DOCX drawing references an empty image resource.")
                    output.counts["images"] += 1
                if STORY.fullmatch(name):
                    _read_story(root, name, rels, output)
        Document(path)
    except EngineError:
        raise
    except (BadZipFile, etree.XMLSyntaxError, KeyError, OSError, PackageNotFoundError, ValueError) as exc:
        raise EngineError("The DOCX could not be reopened as a valid Word package.") from exc
    output.counts["native_tables"] = len(output.tables)
    output.counts["sections"] = len(output.sections)
    return output
