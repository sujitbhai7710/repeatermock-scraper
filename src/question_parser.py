"""
Parse RSC (React Server Component) flight payload from RepeaterMock's /attempt page.

The /attempt page HTML contains <script> tags with self.__next_f.push([1,"..."]) calls.
Each chunk is a JSON-escaped string. Combined, they form the RSC flight payload
which contains all question objects embedded as JSON.

Each question object looks like:
{
  "isNum": false,
  "type": "mcq",
  "negMarks": 0.5,
  "posMarks": 2,
  "_id": "6901f8b14d79a5a4a1ddefd0",
  "en": {
    "value": "<p>Question text in HTML...</p>",
    "options": [{"prompt": "1", "value": "Option A"}, ...]
  },
  "hn": { "value": "...", "options": [...] },
  "te": { ... },  // Telugu
  "mr": { ... },  // Marathi
  ...
  "SSNo": 1,      // Section number
  "QSNo": 1,      // Question number within section
}
"""
import html as html_module
import json
import re
from typing import Any


def extract_flight_payload(html: str) -> str:
    """
    Extract the RSC flight payload from a Next.js page's HTML.

    The payload is split across multiple <script> tags:
        self.__next_f.push([1,"chunk1"])
        self.__next_f.push([1,"chunk2"])
        ...

    Each chunk is a JSON-escaped string. We unescape and concatenate them.
    """
    # Find all flight payload chunks
    chunks = re.findall(r'self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)', html)
    if not chunks:
        return ""

    payload = ""
    for chunk in chunks:
        try:
            # The chunk is a JSON-escaped string — json.loads will unescape it
            unescaped = json.loads(f'"{chunk}"')
        except json.JSONDecodeError:
            # Fallback: manual unescape
            unescaped = chunk.replace('\\"', '"').replace('\\n', '\n').replace('\\t', '\t')
        payload += unescaped

    return payload


def parse_question_objects(payload: str) -> list[dict[str, Any]]:
    """
    Parse all question objects from the RSC flight payload.

    Question objects start with {"isNum":false,"type":"mcq" (or "isNum":true for numerical).
    We use a manual brace-counting parser to extract each complete JSON object.
    """
    # Find all positions where a question object starts
    q_starts = [m.start() for m in re.finditer(r'\{"isNum":(?:false|true),"type":"mcq"', payload)]
    if not q_starts:
        return []

    questions = []
    for start in q_starts:
        # Find the matching closing brace by counting depth
        depth = 0
        in_string = False
        escape = False
        end = start

        for j in range(start, len(payload)):
            c = payload[j]
            if escape:
                escape = False
                continue
            if c == '\\':
                escape = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    end = j + 1
                    break

        q_str = payload[start:end]
        try:
            q = json.loads(q_str)
            questions.append(q)
        except json.JSONDecodeError as e:
            # Skip malformed questions
            print(f"  Warning: Failed to parse question at pos {start}: {e}")
            continue

    return questions


def thorough_unescape(text: str) -> str:
    """
    Unescape HTML entities, handling double-escaping.
    
    RepeaterMock option values are often double-escaped:
      &lt;span class=&quot;math-tex&quot;&gt;\\(\\frac{1}{4}\\)&lt;/span&gt;
    After one unescape:
      <span class="math-tex">\\(\\frac{1}{4}\\)</span>
    We need to unescape until stable.
    """
    if not text:
        return text
    prev = None
    current = text
    # Unescape up to 3 times to handle double/triple escaping
    for _ in range(3):
        if current == prev:
            break
        prev = current
        current = html_module.unescape(current)
    return current


def clean_question(q: dict[str, Any]) -> dict[str, Any]:
    """
    Clean a raw question object into a structured format.

    Extracts only the fields we need:
    - id, type, marks, section, question number
    - Multilingual question text + options (en, hi, te, mr, bn, etc.)
    
    Handles double-escaped HTML entities in option values.
    """
    # Language field mapping (RepeaterMock uses ISO 639-1 / custom codes)
    lang_fields = {
        "en": "en", "hi": "hn", "te": "te", "mr": "mr", "bn": "bn",
        "ml": "ml", "gu": "gu", "kn": "kn", "ta": "ta", "or": "or",
        "as": "as", "ks": "ks", "kok": "kok", "mni": "mni", "ne": "ne",
        "pa": "pa", "sd": "sd", "ur": "ur", "sat": "sat", "mai": "mai",
        "brx": "brx", "doi": "doi", "sa": "sa", "grt": "grt", "kha": "kha",
        "lus": "lus", "bo": "bo", "trp": "trp",
    }

    languages = {}
    for lang_code, field_name in lang_fields.items():
        lang_data = q.get(field_name, {})
        if isinstance(lang_data, dict) and lang_data.get("value"):
            options = lang_data.get("options", [])
            languages[lang_code] = {
                "question": thorough_unescape(lang_data.get("value", "")),
                "options": [
                    {"prompt": o.get("prompt", ""), "value": thorough_unescape(o.get("value", ""))}
                    for o in options
                ] if options else [],
            }

    return {
        "id": q.get("_id", ""),
        "type": q.get("type", "mcq"),
        "isNumerical": q.get("isNum", False),
        "posMarks": q.get("posMarks", 2),
        "negMarks": q.get("negMarks", 0.5),
        "skipMarks": q.get("skipMarks", 0),
        "section": q.get("SSNo", 1),
        "subsection": q.get("SSSNo", 0),
        "questionNo": q.get("QSNo", 0),
        "languages": languages,
    }


def parse_attempt_page(html: str) -> dict[str, Any]:
    """
    Parse a RepeaterMock /attempt page HTML.

    Returns:
        {
            "questions": [...],  # list of cleaned question objects
            "raw_count": int,    # number of raw question objects found
            "payload_size": int, # size of flight payload
        }
    """
    payload = extract_flight_payload(html)
    if not payload:
        return {"questions": [], "raw_count": 0, "payload_size": 0}

    raw_questions = parse_question_objects(payload)
    cleaned = [clean_question(q) for q in raw_questions]

    return {
        "questions": cleaned,
        "raw_count": len(raw_questions),
        "payload_size": len(payload),
    }
