"""Find the article in a web page and return it as clean paragraphs.

Pages wrap their text in menus, banners, share buttons, and comment threads. Like a
browser's reader mode, this keeps only the main text:

1. The page is parsed into a small tree; scripts, forms, navigation, and elements
   whose class or id says they are clutter (``sidebar``, ``share``, ...) are dropped.
2. The element holding most of the paragraph text is chosen as the article (an
   ``<article>`` or ``<main>`` element wins when it holds enough text).
3. Its headings, paragraphs, list items, and quotes become the paragraphs read
   aloud; link lists (menus, "related stories") are skipped.
"""

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

from pdf_reader.sources.models import SourceError, TextSource

_SKIP_TAGS = frozenset(
    [
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "canvas",
        "iframe",
        "form",
        "button",
        "input",
        "select",
        "textarea",
        "nav",
        "aside",
        "figure",
        "menu",
        "dialog",
        "object",
        "embed",
        "video",
        "audio",
        "picture",
        "map",
        "head",
    ]
)
_VOID_TAGS = frozenset(
    [
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    ]
)
_BLOCK_TAGS = frozenset(
    [
        "p",
        "div",
        "section",
        "article",
        "main",
        "header",
        "footer",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "ul",
        "ol",
        "dl",
        "dt",
        "dd",
        "blockquote",
        "pre",
        "table",
        "tr",
        "td",
        "th",
        "caption",
        "figcaption",
        "address",
        "hr",
        "br",
        "body",
    ]
)
_HEADINGS = frozenset(["h1", "h2", "h3", "h4", "h5", "h6"])
_PARAGRAPH_TAGS = frozenset(["p", "pre", "blockquote", "li", "dd", "td"])
_CLUTTER = re.compile(
    r"(?:^|[\s_-])(?:comments?|share|sharing|social|related|recommended|promo|sidebar|"
    r"footer|navbar|nav|menu|cookies?|consent|banner|subscribe|newsletter|advert|"
    r"advertisement|ads?|sponsored?|popup|modal|breadcrumbs?|masthead|signup|login|"
    r"toolbar|tags|paywall|outbrain|taboola|dropdown|noprint|catlinks|editsection|"
    r"hatnote|sitesub|reflist|references|skip|visually|sr)(?:$|[\s_-])",
    re.IGNORECASE,
)
_MIN_PARAGRAPH_CHARS = 25
_MIN_ARTICLE_CHARS = 400
_SPACES = re.compile(r"\s+")


@dataclass(eq=False)
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: "_Node | None"
    children: list["_Node | str"] = field(default_factory=list)
    _length: int = -1

    def text_length(self) -> int:
        """Return how many characters of text this element holds (cached)."""
        if self._length < 0:
            # Scripts and styles hold no readable text, however long they are.
            self._length = sum(
                len(c.strip())
                if isinstance(c, str)
                else (0 if c.tag in _SKIP_TAGS else c.text_length())
                for c in self.children
            )
        return self._length

    def elements(self) -> "list[_Node]":
        """Return this element and all elements inside it, in document order."""
        found = [self]
        for child in self.children:
            if isinstance(child, _Node):
                found.extend(child.elements())
        return found


class _TreeBuilder(HTMLParser):
    """Builds a forgiving element tree (unclosed tags are closed by their parents)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self._stack = [self.root]
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_title = False
        self._title_done = False  # Only the page's own <title>, not those in icons.

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name: value or "" for name, value in attrs}
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and "content" in values:
                self.meta[key.lower()] = values["content"]
        if tag == "title" and not self._title_done and "svg" not in self._open_tags():
            self._in_title = True
        node = _Node(tag, values, self._stack[-1])
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag not in _VOID_TAGS and self._stack[-1].tag == tag:
            self._stack.pop()

    def _open_tags(self) -> set[str]:
        return {node.tag for node in self._stack}

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self._in_title = False
            self._title_done = True
        for depth in range(len(self._stack) - 1, 0, -1):
            if self._stack[depth].tag == tag:
                del self._stack[depth:]
                return

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        self._stack[-1].children.append(data)


def extract_article(html: str, fallback_title: str = "Web page") -> TextSource:
    """Return the main text of a web page.

    Args:
        html: The page's HTML.
        fallback_title: Title to use if the page has none.

    Raises:
        SourceError: No readable text was found.
    """
    builder = _TreeBuilder()
    builder.feed(html)
    builder.close()
    root = builder.root
    _remove_clutter(root)
    article = _choose_article(root)
    paragraphs = _paragraphs(article) if article is not None else []
    if not paragraphs:
        raise SourceError(
            "No readable text was found on this page. It may need a browser to show its "
            "content, or it may be mostly pictures or video."
        )
    title = _title(builder, root) or fallback_title
    if _plain(paragraphs[0]) != _plain(title):
        paragraphs.insert(0, title)
    return TextSource(title, tuple(paragraphs))


def _remove_clutter(root: _Node) -> None:
    """Drop elements that are never part of the article."""
    total = max(root.text_length(), 1)
    for node in root.elements():
        parent = node.parent
        if parent is None:
            continue
        if node.tag in _SKIP_TAGS or node.attrs.get("hidden") is not None or _is_clutter(node):
            # Never drop a wrapper that holds most of the page (a misleading class name).
            if node.tag not in _SKIP_TAGS and node.text_length() > 0.5 * total:
                continue
            if node.tag in ("header", "footer") and _inside(node, ("article", "main")):
                continue
            if node in parent.children:
                parent.children.remove(node)
    _reset_lengths(root)


def _is_clutter(node: _Node) -> bool:
    if node.tag in ("header", "footer") and not _inside(node, ("article", "main")):
        return True
    if node.tag in ("article", "main", "body", "html"):
        return False
    role = node.attrs.get("role", "")
    if role in ("navigation", "banner", "complementary", "contentinfo", "dialog"):
        return True
    names = f"{node.attrs.get('class', '')} {node.attrs.get('id', '')}"
    style = node.attrs.get("style", "").replace(" ", "").lower()
    return bool(_CLUTTER.search(names)) or "display:none" in style


def _inside(node: _Node, tags: tuple[str, ...]) -> bool:
    parent = node.parent
    while parent is not None:
        if parent.tag in tags:
            return True
        parent = parent.parent
    return False


def _reset_lengths(root: _Node) -> None:
    for node in root.elements():
        node._length = -1


def _choose_article(root: _Node) -> _Node | None:
    """Pick the element that holds the article's paragraphs."""
    elements = root.elements()
    for tag in ("article", "main"):
        candidates = [n for n in elements if n.tag == tag]
        if len(candidates) == 1 and _paragraph_chars(candidates[0]) >= _MIN_ARTICLE_CHARS:
            return candidates[0]
    scores: dict[int, float] = {}
    nodes: dict[int, _Node] = {}
    paragraph_total = 0
    for node in elements:
        if node.tag not in _PARAGRAPH_TAGS:
            continue
        length = node.text_length()
        if length < _MIN_PARAGRAPH_CHARS:
            continue
        paragraph_total += length
        text = _inline_text(node)
        score = 1.0 + text.count(",") + min(length / 100, 3.0)
        for share, ancestor in ((1.0, node.parent), (0.5, _grandparent(node))):
            if ancestor is not None:
                scores[id(ancestor)] = scores.get(id(ancestor), 0.0) + score * share
                nodes[id(ancestor)] = ancestor
    if not scores:
        return root
    best = nodes[max(scores, key=lambda key: scores[key])]
    # An article split into several sections: widen until it holds most of the text.
    while best.parent is not None and _paragraph_chars(best) < 0.6 * paragraph_total:
        best = best.parent
    return best


def _grandparent(node: _Node) -> _Node | None:
    return node.parent.parent if node.parent is not None else None


def _paragraph_chars(node: _Node) -> int:
    return sum(
        n.text_length()
        for n in node.elements()
        if n.tag in _PARAGRAPH_TAGS and n.text_length() >= _MIN_PARAGRAPH_CHARS
    )


def _inline_text(node: _Node) -> str:
    parts: list[str] = []

    def walk(current: _Node) -> None:
        for child in current.children:
            if isinstance(child, str):
                parts.append(child)
            else:
                walk(child)

    walk(node)
    return _clean("".join(parts))


def _paragraphs(article: _Node) -> list[str]:
    """Break the article into paragraphs at block elements, skipping link lists."""
    paragraphs: list[str] = []
    buffer: list[tuple[str, bool]] = []  # (text, inside a link)

    def flush() -> None:
        text = _clean("".join(t for t, _ in buffer))
        linked = sum(len(t.strip()) for t, in_link in buffer if in_link)
        buffer.clear()
        if not text or not any(c.isalnum() for c in text):
            return
        if linked > 0.6 * len(text) and len(text) < 200:
            return  # A menu entry or "related story" link, not prose.
        paragraphs.append(text)

    def walk(node: _Node, in_link: bool) -> None:
        for child in node.children:
            if isinstance(child, str):
                buffer.append((child, in_link))
                continue
            block = child.tag in _BLOCK_TAGS
            if block:
                flush()
            walk(child, in_link or child.tag == "a")
            if block:
                flush()

    walk(article, False)
    flush()
    return paragraphs


def _title(builder: _TreeBuilder, root: _Node) -> str:
    """Return the article's title: its heading, or the title the page declares.

    Declared titles often carry the site's name ("Lighthouse - Wikipedia"); when the
    main heading is part of the declared title, the heading alone is used.
    """
    declared = [
        _clean(text)
        for text in (
            builder.meta.get("og:title", ""),
            builder.meta.get("twitter:title", ""),
            builder.title,
        )
    ]
    declared = [text for text in declared if text]
    heading_node = next((n for n in root.elements() if n.tag == "h1"), None)
    heading = _inline_text(heading_node) if heading_node is not None else ""
    if heading and (not declared or any(_plain(heading) in _plain(d) for d in declared)):
        return heading
    return declared[0] if declared else heading


def _clean(text: str) -> str:
    """Collapse whitespace and drop permalink marks ("\u00b6") that pages add to headings."""
    return _SPACES.sub(" ", text.replace("\u00b6", "")).strip()


def _plain(text: str) -> str:
    return re.sub(r"\W+", "", text).lower()
