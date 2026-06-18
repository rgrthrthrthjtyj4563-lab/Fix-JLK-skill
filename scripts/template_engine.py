"""Template engine primitives: cross-run text replacement helpers.

These primitives operate on raw OOXML ``w:p`` elements (parsed via
``xml.etree.ElementTree`` / ``python-docx``'s ``element`` API). They are kept
deliberately small so the renderer can compose them without coupling to a
specific document.

Background: Word frequently splits a single logical placeholder such as
``{{field.meta.product}}`` across multiple ``w:r``/``w:t`` elements as soon as
formatting changes mid-string. A naive ``t.text.replace(...)`` therefore
misses the placeholder. The functions in this module flatten the runs to
search across the boundary, then write the replacement back into the first
run while preserving its style and clearing the remaining sibling text nodes.

Drawings, bookmarks and field codes that share a paragraph with placeholder
text MUST survive replacement; ``safe_replace_in_paragraph`` skips runs that
contain a ``w:drawing`` so the chart/image is not destroyed.

Compatibility note: these primitives were previously private to
``scripts/render_from_template.py`` (with a leading underscore). Extracting
them allows the placeholder migration tasks (5-8) to depend on a small,
well-tested surface without dragging in the entire renderer.
"""
from __future__ import annotations

from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def get_paragraph_text(p_element) -> str:
    """Extract concatenated plain text from a ``w:p`` element."""
    texts: list[str] = []
    for r in p_element.findall(qn("w:r")):
        for t in r.findall(qn("w:t")):
            texts.append(t.text or "")
    return "".join(texts)


def paragraph_has_drawing(p_element) -> bool:
    """Return True if the paragraph contains a ``w:drawing`` or ``w:pict``."""
    return any(
        run.find(qn("w:drawing")) is not None or run.find(qn("w:pict")) is not None
        for run in p_element.findall(qn("w:r"))
    )


def set_run_text(run_element, text: str) -> None:
    """Set the text of a single ``w:r`` element, preserving xml:space."""
    for t in run_element.findall(qn("w:t")):
        t.text = text
        t.set(qn("xml:space"), "preserve")
        return
    # No existing w:t -> append a new one preserving whitespace.
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    run_element.append(t)


def set_paragraph_text(p_element, text: str) -> None:
    """Replace all runs in a paragraph with a single fresh run holding ``text``.

    This is the destructive variant; any prior run-level styling is lost. Use
    :func:`overwrite_paragraph_text_preserve_run_style` instead when the
    caller wants to keep the first run's formatting.
    """
    for r in list(p_element.findall(qn("w:r"))):
        p_element.remove(r)
    r = OxmlElement("w:r")
    rPr = OxmlElement("w:rPr")
    r.append(rPr)
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = text
    r.append(t)
    p_element.insert(0, r)


def overwrite_paragraph_text_preserve_run_style(p_element, text: str) -> None:
    """Overwrite paragraph text while preserving the first text run's style.

    Drawings inside the paragraph are kept intact; only ``w:t`` nodes inside
    sibling text runs are cleared. The replacement text is written into the
    first non-drawing run's ``w:t`` so the original ``w:rPr`` is reused.
    """
    runs = p_element.findall(qn("w:r"))
    text_runs = [r for r in runs if r.find(qn("w:drawing")) is None]
    if not text_runs:
        set_paragraph_text(p_element, text)
        return

    first_run = text_runs[0]
    first_text = first_run.find(qn("w:t"))
    if first_text is None:
        first_text = OxmlElement("w:t")
        first_run.append(first_text)
    first_text.set(qn("xml:space"), "preserve")
    first_text.text = text

    for run in text_runs[1:]:
        for t in run.findall(qn("w:t")):
            t.text = ""


def replace_text_across_runs(p_element, old_text: str, new_text: str) -> bool:
    """Replace ``old_text`` with ``new_text`` even when split across runs.

    Returns ``True`` if the replacement was performed, ``False`` if the
    paragraph did not contain ``old_text`` once flattened. The replaced text
    is written into the *first* ``w:t`` so its run-level style is preserved;
    siblings that contributed to the original split are cleared.
    """
    full_text = get_paragraph_text(p_element)
    if old_text not in full_text:
        return False

    runs = p_element.findall(qn("w:r"))
    if not runs:
        return False

    segments: list = []
    for r in runs:
        for t in r.findall(qn("w:t")):
            segments.append((r, t))
    if not segments:
        return False

    full = "".join(t.text or "" for _, t in segments)
    full = full.replace(old_text, new_text)

    first_t = segments[0][1]
    first_t.text = full
    first_t.set(qn("xml:space"), "preserve")
    for _, t in segments[1:]:
        t.text = ""
    return True


def replace_text_in_paragraph(p_element, old: str, new: str) -> bool:
    """Replace ``old`` with ``new`` in a paragraph that has NO drawing.

    This is the destructive flatten-and-rewrite variant: it collapses the
    paragraph to a single run and therefore loses run-level styling. Callers
    that need to preserve formatting and may encounter drawings should use
    :func:`safe_replace_in_paragraph` instead.
    """
    full = get_paragraph_text(p_element)
    if old not in full:
        return False
    new_full = full.replace(old, new)
    for r in list(p_element.findall(qn("w:r"))):
        p_element.remove(r)
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.set(qn("xml:space"), "preserve")
    t.text = new_full
    r.append(t)
    p_element.append(r)
    return True


def safe_replace_in_paragraph(p_element, old: str, new: str) -> None:
    """Replace ``old`` with ``new`` in a paragraph, preserving any drawings.

    If the paragraph contains a ``w:drawing`` (chart or image), the function
    iterates only the text runs and rewrites their ``w:t`` text in-place so
    the drawing element is left untouched. Otherwise the simpler
    :func:`replace_text_in_paragraph` is used.
    """
    has_drawing = any(
        r.find(qn("w:drawing")) is not None
        for r in p_element.findall(qn("w:r"))
    )
    if has_drawing:
        for r in p_element.findall(qn("w:r")):
            if r.find(qn("w:drawing")) is not None:
                continue
            for t in r.findall(qn("w:t")):
                if t.text and old in t.text:
                    t.text = t.text.replace(old, new)
                    t.set(qn("xml:space"), "preserve")
    else:
        replace_text_in_paragraph(p_element, old, new)
