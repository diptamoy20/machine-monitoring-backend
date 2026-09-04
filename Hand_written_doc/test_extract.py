"""
Quick test script: handwritten trade-slip -> structured data.

SETUP (once):
    pip install anthropic --break-system-packages     (Windows: drop the flag)
    setx ANTHROPIC_API_KEY "your-key-here"             (Windows, then reopen terminal)
    export ANTHROPIC_API_KEY="your-key-here"           (Mac/Linux)

RUN:
    python test_extract.py path/to/image.jpg
"""

import base64
import json
import sys
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

load_dotenv()

PROMPT = """You are reading a handwritten trade/inventory note. It may mix Bengali and
English, with measurements in feet/inches/mm, weights in kg/ton, piece counts ("pc"),
gauge specs, and vendor names.

Extract every distinct line item you can find as a JSON array. Each item should have:
- "dimension": the size/length spec as written (e.g. "5X8", "17 ft")
- "spec": any gauge/thickness/profile description
- "quantity": the quantity or weight value as written
- "unit": the unit (pc, kg, ton, etc.)
- "notes": anything else relevant (vendor name, date, price, short/balance notes)
- "confidence": "high" or "low" -- mark "low" if the handwriting is genuinely ambiguous

Also include one summary object at the end with "vendor" (business name on the page, if
visible) and "date" (if visible).

Respond with ONLY a valid JSON array. No prose, no markdown fences.
"""


def main():
    if len(sys.argv) != 2:
        print("Usage: python test_extract.py path/to/image.jpg")
        sys.exit(1)

    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        sys.exit(1)

    media_type = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    image_bytes = path.read_bytes()
    b64 = base64.b64encode(image_bytes).decode("utf-8")

    client = Anthropic()  # reads ANTHROPIC_API_KEY from env

    print(f"Reading {path.name} ...")
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": PROMPT},
                ],
            }
        ],
    )

    raw = resp.content[0].text.strip().replace("```json", "").replace("```", "").strip()

    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        print("Model did not return clean JSON. Raw output:\n")
        print(raw)
        sys.exit(1)

    print("\n" + "=" * 60)
    for item in items:
        if not item.get("dimension"):
            # summary object
            print(f"Vendor: {item.get('vendor') or '—'}   Date: {item.get('date') or '—'}")
            print("=" * 60)
            continue
        flag = "[LOW CONF]" if item.get("confidence") == "low" else ""
        print(
            f"{item.get('dimension') or '—':<12} "
            f"{item.get('spec') or '—':<18} "
            f"{item.get('quantity') or '—'} {item.get('unit') or '':<6} "
            f"{item.get('notes') or '':<20} {flag}"
        )

    out_path = path.with_suffix(".json")
    out_path.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nFull JSON saved to {out_path}")


if __name__ == "__main__":
    main()