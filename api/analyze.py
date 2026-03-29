"""
Vercel Serverless Function — Wordle Screenshot Analyzer

POST /api/analyze
- Accepts: multipart/form-data with 'image' field
- Returns: JSON with answer, guesses, flower counts, and poem — ready for wordle-garden

Uses Gemini 2.5 Flash for vision analysis + poem generation.
"""

import os
import json
import base64
import tempfile
from http.server import BaseHTTPRequestHandler

from google import genai
from PIL import Image

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_NAME = "gemini-2.5-flash"

WORDLE_PROMPT = """Look at this Wordle screenshot. Read each row of the grid from top to bottom.

For each row, tell me:
1. The 5-letter word
2. The color of each tile — only use: "green", "yellow", or "gray"

Look carefully at each tile's background color:
- Green = bright green
- Yellow = gold/amber/mustard
- Gray = dark gray or charcoal

The last filled row is the answer — include it in the guesses array with all "green". Include ALL filled rows in the guesses array. Ignore empty rows. Ignore the keyboard.

Return ONLY valid JSON in this exact format, all words UPPERCASE:

{
  "answer": "XXXXX",
  "guesses": [
    { "word": "XXXXX", "colors": ["gray", "yellow", "green", "gray", "gray"] }
  ]
}"""

POEM_PROMPT = """You are given a Wordle game. Write a poem based on the guesses.

Guesses (in order):
{guesses_text}

Answer: {answer}

Write a poem where:
- Number of stanzas = number of guesses ({num_guesses})
- Each stanza is exactly 2 lines
- Each stanza revolves around that guess word, woven naturally into the line — not as a letter hint
- The sentiment of each stanza mirrors the progress of that guess:
  lost/searching for poor guesses, hopeful for partial hits, triumphant for the win
- Do NOT reference counts, numbers, or quantities of letters found — let the emotion carry the progress
- No references to Wordle, grids, tiles, letters, or puzzles
- The poem should read as a standalone piece about perseverance or discovery

Return ONLY the poem text. Separate stanzas with a blank line. No title, no explanation."""

# Map colors to wordle-garden result format
COLOR_TO_RESULT = {
    "green": "correct",
    "yellow": "present",
    "gray": "absent",
}


def get_client():
    return genai.Client(api_key=GEMINI_API_KEY)


def analyze_screenshot(image_path: str) -> dict:
    """Send screenshot to Gemini and parse structured game data."""
    client = get_client()
    img = Image.open(image_path)

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=[WORDLE_PROMPT, img],
    )
    raw = response.text.strip().removeprefix("```json").removesuffix("```").strip()
    return json.loads(raw)


def generate_poem(data: dict) -> str:
    """Generate a poem from the extracted game data."""
    client = get_client()

    guesses_text = "\n".join(
        f"{i+1}. {g['word']} — {', '.join(g['colors'])}"
        for i, g in enumerate(data["guesses"])
    )

    prompt = POEM_PROMPT.format(
        guesses_text=guesses_text,
        answer=data["answer"],
        num_guesses=len(data["guesses"]),
    )

    response = client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )
    return response.text.strip()


def to_garden_format(data: dict, poem: str) -> dict:
    """Convert Gemini output to wordle-garden JSON format."""
    guesses = []
    green_count = 0
    yellow_count = 0

    for i, g in enumerate(data["guesses"]):
        colors = g["colors"]
        result = [COLOR_TO_RESULT[c] for c in colors]
        guesses.append({"word": g["word"].upper(), "result": result})

        # Count flowers (exclude final winning row)
        is_last = i == len(data["guesses"]) - 1
        if not is_last:
            for c in colors:
                if c == "green":
                    green_count += 1
                elif c == "yellow":
                    yellow_count += 1

    return {
        "answer": data["answer"].upper(),
        "guesses": guesses,
        "poem": poem,
        "green_count": green_count,
        "yellow_count": yellow_count,
    }


class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if not GEMINI_API_KEY:
            self._respond(500, {"error": "GEMINI_API_KEY not configured"})
            return

        content_type = self.headers.get("Content-Type", "")

        try:
            if "multipart/form-data" in content_type:
                image_data = self._parse_multipart()
            elif "application/json" in content_type:
                image_data = self._parse_json_base64()
            else:
                self._respond(400, {"error": "Expected multipart/form-data or application/json"})
                return

            if not image_data:
                self._respond(400, {"error": "No image provided"})
                return

            # Write to temp file for PIL
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                f.write(image_data)
                temp_path = f.name

            try:
                raw = analyze_screenshot(temp_path)
                poem = generate_poem(raw)
                result = to_garden_format(raw, poem)
                self._respond(200, result)
            finally:
                os.unlink(temp_path)

        except json.JSONDecodeError:
            self._respond(422, {"error": "Could not parse Gemini response as JSON"})
        except Exception as e:
            err = str(e).lower()
            if "429" in err or "rate" in err or "quota" in err or "too many" in err:
                self._respond(429, {"error": "rate_limit"})
            else:
                self._respond(500, {"error": str(e)})

    def do_OPTIONS(self):
        """Handle CORS preflight."""
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def _parse_multipart(self) -> bytes:
        """Extract image bytes from multipart form data."""
        import cgi
        form = cgi.FieldStorage(
            fp=self.rfile,
            headers=self.headers,
            environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]},
        )
        file_item = form["image"]
        if file_item.file:
            return file_item.file.read()
        return None

    def _parse_json_base64(self) -> bytes:
        """Extract image bytes from JSON { "image": "<base64>" }."""
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length))
        return base64.b64decode(body["image"])

    def _respond(self, status: int, data: dict):
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
