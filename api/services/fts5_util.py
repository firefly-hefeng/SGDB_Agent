"""FTS5 query sanitisation helper.

User-supplied `text_search` strings hit SQLite's FTS5 MATCH operator,
which has its own mini-grammar: bare punctuation like `;`, `--`, `'`,
parentheses, brackets, and the words `AND`/`OR`/`NOT` all have meaning.
Passing user input verbatim into MATCH produces SQL execution errors
(observed Phase 28.E fuzz: `text_search="'; DROP TABLE …"` → 500
"fts5: syntax error near \"'\"").

The robust fix is to *tokenize* on whitespace, escape internal double
quotes, and emit each token as a quoted FTS5 phrase joined by spaces
(implicit AND). FTS5 treats `"..."` as an unparsed phrase, so any
punctuation inside is safe.

Examples
--------
    safe('hello')               -> '"hello"'
    safe('hello world')         -> '"hello" "world"'
    safe('alzheimer 2024')      -> '"alzheimer" "2024"'
    safe('"; DROP TABLE -- ')   -> '"DROP" "TABLE"'        (punctuation stripped)
    safe('')                    -> ''                       (caller skips)
    safe('   ')                 -> ''

Notes
-----
We strip non-alphanumeric characters from each token before quoting so
that pathological inputs like `\\` or unmatched `"` (which would break
the FTS5 quoter itself) can't slip through. Unicode letters/digits are
preserved (Chinese, accents, etc.).
"""

from __future__ import annotations

import re

# Regex matches one "word" of unicode alphanumerics + dashes + dots, of
# any length. Anything else (quotes, semicolons, brackets, control
# chars) is treated as a separator and dropped.
_FTS5_TOKEN_RE = re.compile(r"[\w\-.]+", re.UNICODE)


def safe_fts5_query(user_text: str | None) -> str:
    """Return an FTS5-safe MATCH expression for arbitrary user input.

    Empty / whitespace-only / punctuation-only input returns an empty
    string; callers should treat that as "no full-text filter".
    """
    if not user_text:
        return ""
    tokens = _FTS5_TOKEN_RE.findall(user_text)
    # Defensive: even though our regex excludes `"`, an exotic unicode
    # situation could still slip a quote in. Replace just in case.
    quoted = [f'"{t.replace(chr(34), "")}"' for t in tokens if t]
    return " ".join(quoted)
