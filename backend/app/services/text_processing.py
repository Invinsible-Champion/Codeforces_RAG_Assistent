"""
Text processing utilities: HTML cleaning, section extraction, semantic chunking,
and editorial content extraction.
"""
import re
from typing import Optional
from bs4 import BeautifulSoup, Tag, NavigableString
import tiktoken


def html_to_clean_text(html: str) -> str:
    """Convert HTML to clean plaintext while preserving structure."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")

    # Remove script/style tags
    for tag in soup(["script", "style"]):
        tag.decompose()

    # Replace <br> and block elements with newlines
    for br in soup.find_all("br"):
        br.replace_with("\n")

    for block_tag in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4"]):
        block_tag.insert_before("\n")
        block_tag.insert_after("\n")

    text = soup.get_text()

    # Normalize whitespace
    lines = []
    for line in text.split("\n"):
        cleaned = " ".join(line.split())
        if cleaned:
            lines.append(cleaned)

    return "\n".join(lines)


def extract_problem_sections(html: str) -> dict:
    """
    Parse a Codeforces problem-statement HTML into structured sections.

    Returns dict with keys: title, time_limit, memory_limit, statement,
    input_spec, output_spec, examples, note
    """
    if not html:
        return {}

    soup = BeautifulSoup(html, "html.parser")
    sections = {}

    # Title
    title_elem = soup.select_one(".title")
    if title_elem:
        sections["title"] = title_elem.get_text(strip=True)

    # Time limit
    tl = soup.select_one(".time-limit")
    if tl:
        sections["time_limit"] = tl.get_text(strip=True).replace("time limit per test", "").strip()

    # Memory limit
    ml = soup.select_one(".memory-limit")
    if ml:
        sections["memory_limit"] = ml.get_text(strip=True).replace("memory limit per test", "").strip()

    # Main statement body — the divs directly under .problem-statement
    # that are NOT header, input-spec, output-spec, sample-tests, note
    problem_statement = soup.select_one(".problem-statement")
    if problem_statement:
        statement_parts = []
        for child in problem_statement.children:
            if isinstance(child, Tag):
                classes = child.get("class", [])
                # Skip known sections
                if any(cls in classes for cls in [
                    "header", "input-specification", "output-specification",
                    "sample-tests", "note"
                ]):
                    continue
                text = html_to_clean_text(str(child))
                if text.strip():
                    statement_parts.append(text.strip())

        sections["statement"] = "\n\n".join(statement_parts)

    # Input specification
    input_spec = soup.select_one(".input-specification")
    if input_spec:
        sections["input_spec"] = html_to_clean_text(str(input_spec)).replace("Input", "", 1).strip()

    # Output specification
    output_spec = soup.select_one(".output-specification")
    if output_spec:
        sections["output_spec"] = html_to_clean_text(str(output_spec)).replace("Output", "", 1).strip()

    # Sample tests
    sample_tests = soup.select_one(".sample-tests")
    if sample_tests:
        examples = []
        inputs = sample_tests.select(".input pre")
        outputs = sample_tests.select(".output pre")
        for inp, out in zip(inputs, outputs):
            examples.append({
                "input": inp.get_text(strip=True),
                "output": out.get_text(strip=True),
            })
        sections["examples"] = examples

    # Note
    note = soup.select_one(".note")
    if note:
        sections["note"] = html_to_clean_text(str(note)).replace("Note", "", 1).strip()

    return sections


# ─── Editorial Extraction ────────────────────────────────────────────────────


def extract_editorial_section(html: str, problem_index: str, problem_name: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract HTML and text for a specific problem's editorial.
    """
    if not html:
        return None, None

    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".ttypography") or soup.select_one(".content") or soup.select_one("#pageContent")
    if not content:
        return None, None

    for spoiler in content.select(".spoiler-content"):
        pass

    idx = problem_index.upper()
    name_escaped = re.escape(problem_name)
    problem_patterns = [
        re.compile(rf'^{re.escape(idx)}[\.\s\-—–:]', re.IGNORECASE),
        re.compile(rf'^Problem\s+{re.escape(idx)}[\.\s\-—–:]?', re.IGNORECASE),
        re.compile(rf'\b{re.escape(idx)}[\.\s]', re.IGNORECASE),
        re.compile(rf'{name_escaped}', re.IGNORECASE)
    ]

    next_indices = _get_next_indices(problem_index)
    next_patterns = []
    for nidx in next_indices:
        next_patterns.extend([
            re.compile(rf'^{re.escape(nidx)}[\.\s\-—–:]', re.IGNORECASE),
            re.compile(rf'^Problem\s+{re.escape(nidx)}[\.\s\-—–:]?', re.IGNORECASE)
        ])

    headers = content.find_all(["h1", "h2", "h3", "h4", "h5", "b", "strong", "p"])
    start_element = None
    for header in headers:
        header_text = header.get_text(strip=True)
        if not header_text:
            continue
        for pattern in problem_patterns:
            if pattern.search(header_text):
                start_element = header
                break
        if start_element:
            break

    if not start_element:
        full_text = content.get_text()
        if problem_name in full_text or f"Problem {idx}" in full_text:
            return str(content), _extract_clean_editorial_text(content)
        return None, None

    editorial_parts_html = []
    editorial_parts_text = []
    current = start_element

    while current:
        current = current.next_sibling
        if current is None:
            break

        if isinstance(current, NavigableString):
            text = str(current).strip()
            if text:
                editorial_parts_html.append(str(current))
                editorial_parts_text.append(text)
            continue

        if isinstance(current, Tag):
            current_text = current.get_text(strip=True)
            if current_text and current.name in ["h1", "h2", "h3", "h4", "h5", "b", "strong", "p"]:
                is_next = False
                for np in next_patterns:
                    if np.search(current_text):
                        is_next = True
                        break
                if is_next:
                    break

            elem_text = _extract_element_text(current)
            if elem_text.strip():
                editorial_parts_text.append(elem_text.strip())
            editorial_parts_html.append(str(current))

    if not editorial_parts_text:
        return None, None

    raw_html = "".join(editorial_parts_html)
    raw_text = "\n\n".join(editorial_parts_text)
    
    clean_text = _clean_editorial_text(raw_text)
    
    if clean_text.strip():
        return raw_html, clean_text
    return None, None


def _get_next_indices(current_index: str) -> list[str]:
    """Get possible next problem indices after the current one."""
    idx = current_index.upper()
    next_indices = []

    if len(idx) == 1 and idx.isalpha():
        # Simple letter: A -> B, B -> C, etc.
        next_char = chr(ord(idx) + 1)
        if next_char <= 'Z':
            next_indices.append(next_char)
    elif len(idx) == 2 and idx[0].isalpha() and idx[1].isdigit():
        # Sub-problem: C1 -> C2, C2 -> D
        letter = idx[0]
        num = int(idx[1])
        next_indices.append(f"{letter}{num + 1}")
        next_char = chr(ord(letter) + 1)
        if next_char <= 'Z':
            next_indices.append(next_char)
    else:
        # Fallback: just try next letter
        if idx[0].isalpha():
            next_char = chr(ord(idx[0]) + 1)
            if next_char <= 'Z':
                next_indices.append(next_char)

    return next_indices


def _extract_element_text(element: Tag) -> str:
    """Extract text from an element, including spoiler content."""
    # If this is a spoiler, extract its content
    if "spoiler" in (element.get("class") or []):
        spoiler_content = element.select_one(".spoiler-content")
        if spoiler_content:
            return html_to_clean_text(str(spoiler_content))
        return ""

    return html_to_clean_text(str(element))


def _extract_clean_editorial_text(container: Tag) -> str:
    """Extract clean text from a full editorial container when we can't isolate a problem section."""
    # Remove known noise elements
    for noise_sel in [".roundbox.sidebox", ".second-level-menu", ".comments", ".comment",
                      ".rated-user", "script", "style", ".MathJax_Preview"]:
        for elem in container.select(noise_sel):
            elem.decompose()

    return html_to_clean_text(str(container))


def _clean_editorial_text(text: str) -> str:
    """Clean up extracted editorial text — remove boilerplate lines."""
    lines = text.split("\n")
    cleaned = []

    # Lines to skip (common boilerplate)
    skip_patterns = [
        re.compile(r'^UPD[\s:]*$', re.IGNORECASE),
        re.compile(r'^Author[\s:]*$', re.IGNORECASE),
        re.compile(r'^Preparation[\s:]*$', re.IGNORECASE),
        re.compile(r'^\d+\s+comments?$', re.IGNORECASE),
        re.compile(r'^By\s+\w+,\s+\d+', re.IGNORECASE),  # "By user, 3 years ago"
        re.compile(r'^Codeforces\s+Round', re.IGNORECASE),
        re.compile(r'^\s*$'),  # Empty lines (we'll re-add structure)
    ]

    for line in lines:
        skip = False
        for pattern in skip_patterns:
            if pattern.match(line.strip()):
                skip = True
                break
        if not skip:
            cleaned.append(line)

    return "\n".join(cleaned).strip()


def find_editorial_blog_url(html: str) -> Optional[str]:
    """
    Extract the editorial/tutorial blog URL from a Codeforces contest page.
    Looks for links in the sidebar "Contest Materials" section.
    """
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")

    # Look in sidebar boxes for editorial/tutorial links
    for link in soup.find_all("a", href=True):
        link_text = link.get_text(strip=True).lower()
        href = link["href"]

        # Common editorial link texts
        if any(keyword in link_text for keyword in ["editorial", "tutorial", "analysis", "разбор"]):
            if "/blog/entry/" in href:
                # Make absolute URL
                if href.startswith("/"):
                    return f"https://codeforces.com{href}"
                return href

    return None


# ─── Token Counting & Chunking ──────────────────────────────────────────────


def count_tokens(text: str, model: str = "cl100k_base") -> int:
    """Count tokens in text using tiktoken."""
    try:
        enc = tiktoken.get_encoding(model)
    except Exception:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


def chunk_problem_text(
    sections: dict,
    problem_meta: Optional[dict] = None,
    max_tokens: int = 400,
    editorial_text: Optional[str] = None,
) -> list[dict]:
    """
    Create semantic chunks from extracted problem sections.

    Each chunk contains:
    - chunk_text: The actual text
    - chunk_type: What section it's from (statement, input_spec, etc.)
    - chunk_index: Order within the problem

    Strategy:
    1. Create a "full" chunk with metadata + complete statement for broad retrieval
    2. Create individual section chunks for fine-grained retrieval
    3. If editorial text is available, include it as a dedicated chunk
    """
    chunks = []
    chunk_idx = 0

    # Build metadata prefix for context
    meta_prefix = ""
    if problem_meta:
        parts = []
        if problem_meta.get("contest_id") and problem_meta.get("index"):
            parts.append(f"Problem {problem_meta['contest_id']}{problem_meta['index']}")
        if problem_meta.get("name"):
            parts.append(f"Title: {problem_meta['name']}")
        if problem_meta.get("rating"):
            parts.append(f"Rating: {problem_meta['rating']}")
        if problem_meta.get("tags"):
            parts.append(f"Tags: {', '.join(problem_meta['tags'])}")
        meta_prefix = " | ".join(parts) + "\n\n"

    # Full combined chunk (for broad matching like "give me 1200 greedy problems")
    full_text_parts = [meta_prefix.strip()]
    if sections.get("statement"):
        full_text_parts.append(sections["statement"])
    if sections.get("input_spec"):
        full_text_parts.append(f"Input: {sections['input_spec']}")
    if sections.get("output_spec"):
        full_text_parts.append(f"Output: {sections['output_spec']}")
    if sections.get("note"):
        full_text_parts.append(f"Note: {sections['note']}")

    full_text = "\n\n".join(full_text_parts)

    # If full text is short enough, just use one chunk
    if count_tokens(full_text) <= max_tokens:
        chunks.append({
            "chunk_text": full_text,
            "chunk_type": "full",
            "chunk_index": chunk_idx,
            "token_count": count_tokens(full_text),
        })
        chunk_idx += 1
    else:
        # Split into section-based chunks
        # Always include a summary chunk with metadata
        summary = meta_prefix.strip()
        if sections.get("statement"):
            # Take first ~200 tokens of the statement for the summary
            stmt = sections["statement"]
            if count_tokens(stmt) > 200:
                words = stmt.split()
                truncated = []
                token_count = 0
                for word in words:
                    token_count += count_tokens(word + " ")
                    if token_count > 200:
                        break
                    truncated.append(word)
                summary += "\n\n" + " ".join(truncated) + "..."
            else:
                summary += "\n\n" + stmt

        chunks.append({
            "chunk_text": summary,
            "chunk_type": "summary",
            "chunk_index": chunk_idx,
            "token_count": count_tokens(summary),
        })
        chunk_idx += 1

        # Statement chunk(s) — may need splitting for long statements
        if sections.get("statement"):
            stmt_text = meta_prefix + sections["statement"]
            if count_tokens(stmt_text) <= max_tokens:
                chunks.append({
                    "chunk_text": stmt_text,
                    "chunk_type": "statement",
                    "chunk_index": chunk_idx,
                    "token_count": count_tokens(stmt_text),
                })
                chunk_idx += 1
            else:
                # Split long statements by paragraph
                paragraphs = sections["statement"].split("\n\n")
                current_chunk = meta_prefix
                for para in paragraphs:
                    test_chunk = current_chunk + para + "\n\n"
                    if count_tokens(test_chunk) > max_tokens and current_chunk != meta_prefix:
                        chunks.append({
                            "chunk_text": current_chunk.strip(),
                            "chunk_type": "statement",
                            "chunk_index": chunk_idx,
                            "token_count": count_tokens(current_chunk),
                        })
                        chunk_idx += 1
                        current_chunk = meta_prefix + para + "\n\n"
                    else:
                        current_chunk = test_chunk

                if current_chunk.strip() and current_chunk.strip() != meta_prefix.strip():
                    chunks.append({
                        "chunk_text": current_chunk.strip(),
                        "chunk_type": "statement",
                        "chunk_index": chunk_idx,
                        "token_count": count_tokens(current_chunk),
                    })
                    chunk_idx += 1

        # Input/Output spec chunk
        io_parts = []
        if sections.get("input_spec"):
            io_parts.append(f"Input Specification:\n{sections['input_spec']}")
        if sections.get("output_spec"):
            io_parts.append(f"Output Specification:\n{sections['output_spec']}")
        if io_parts:
            io_text = meta_prefix + "\n\n".join(io_parts)
            chunks.append({
                "chunk_text": io_text,
                "chunk_type": "io_spec",
                "chunk_index": chunk_idx,
                "token_count": count_tokens(io_text),
            })
            chunk_idx += 1

        # Examples chunk
        if sections.get("examples"):
            example_text = meta_prefix + "Examples:\n"
            for i, ex in enumerate(sections["examples"], 1):
                example_text += f"\nExample {i}:\nInput:\n{ex['input']}\nOutput:\n{ex['output']}\n"
            chunks.append({
                "chunk_text": example_text,
                "chunk_type": "example",
                "chunk_index": chunk_idx,
                "token_count": count_tokens(example_text),
            })
            chunk_idx += 1

        # Note chunk
        if sections.get("note"):
            note_text = meta_prefix + f"Note:\n{sections['note']}"
            chunks.append({
                "chunk_text": note_text,
                "chunk_type": "note",
                "chunk_index": chunk_idx,
                "token_count": count_tokens(note_text),
            })
            chunk_idx += 1

    # ── Editorial chunk (the key addition!) ──────────────────────────────────
    if editorial_text and editorial_text.strip():
        editorial_chunk_text = meta_prefix + f"Editorial / Solution Approach:\n\n{editorial_text.strip()}"

        # If editorial is short enough, one chunk
        if count_tokens(editorial_chunk_text) <= max_tokens:
            chunks.append({
                "chunk_text": editorial_chunk_text,
                "chunk_type": "editorial",
                "chunk_index": chunk_idx,
                "token_count": count_tokens(editorial_chunk_text),
            })
            chunk_idx += 1
        else:
            # Split editorial into multiple chunks by paragraph
            paragraphs = editorial_text.strip().split("\n\n")
            current_chunk = meta_prefix + "Editorial / Solution Approach:\n\n"
            for para in paragraphs:
                test_chunk = current_chunk + para + "\n\n"
                if count_tokens(test_chunk) > max_tokens and current_chunk != meta_prefix + "Editorial / Solution Approach:\n\n":
                    chunks.append({
                        "chunk_text": current_chunk.strip(),
                        "chunk_type": "editorial",
                        "chunk_index": chunk_idx,
                        "token_count": count_tokens(current_chunk),
                    })
                    chunk_idx += 1
                    current_chunk = meta_prefix + "Editorial (continued):\n\n" + para + "\n\n"
                else:
                    current_chunk = test_chunk

            if current_chunk.strip():
                chunks.append({
                    "chunk_text": current_chunk.strip(),
                    "chunk_type": "editorial",
                    "chunk_index": chunk_idx,
                    "token_count": count_tokens(current_chunk),
                })
                chunk_idx += 1

    return chunks
