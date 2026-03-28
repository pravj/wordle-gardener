"""
Local test for the analyze endpoint logic.

Usage:
    python test_local.py path/to/screenshot.png
"""

import os
import sys
import json

# Use the same key from wordle_analyzer.py or env var
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    print("Set GEMINI_API_KEY env var first")
    sys.exit(1)

os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

from api.analyze import analyze_screenshot, generate_poem, to_garden_format


def main():
    if len(sys.argv) < 2:
        print("Usage: python test_local.py <path_to_screenshot>")
        sys.exit(1)

    image_path = sys.argv[1]
    if not os.path.exists(image_path):
        print(f"File not found: {image_path}")
        sys.exit(1)

    print("Analyzing...\n")

    raw = analyze_screenshot(image_path)
    print("Generating poem...\n")
    poem = generate_poem(raw)
    result = to_garden_format(raw, poem)

    print(f"✓ answer: {result['answer']}, guesses: {len(result['guesses'])}")
    print(f"  flowers: {result['green_count']} green, {result['yellow_count']} yellow\n")

    for g in result["guesses"]:
        colors = " ".join(
            "🟩" if r == "correct" else "🟨" if r == "present" else "⬛"
            for r in g["result"]
        )
        print(f"  {g['word']}  {colors}")

    print(f"\nPoem:\n{result['poem']}")


if __name__ == "__main__":
    main()
