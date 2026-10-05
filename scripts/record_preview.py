"""Record the README preview (docs/media/live-view.gif): tracks moving, then the agent
answering the drone question.

Needs a running live view on port 8011 (`upchirp live --scene courtyard --port 8011`) and
Playwright (`pip install playwright && python -m playwright install chromium`). Waits for a
drone-like track, about 90 s into the courtyard. Usage:

    python scripts/record_preview.py docs/media/live-view.gif
"""

import io
import json
import sys
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8011"
OUT = sys.argv[1]
QUESTION = "How many drone-like tracks crossed in the last 10 minutes, and which came closest?"


def drone_on_map() -> bool:
    with urllib.request.urlopen(f"{URL}/api/tracks?label=drone_like&last_minutes=0.1") as r:
        return json.load(r)["track_count"] > 0


frames: list[tuple[Image.Image, int]] = []  # (image, ms to show)
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 760}, device_scale_factor=1)
    page.goto(URL)
    for _ in range(240):  # wait until a drone-like track is live, up to 4 minutes
        if drone_on_map():
            break
        time.sleep(1)
    time.sleep(2)

    def grab(ms: int) -> None:
        frames.append((Image.open(io.BytesIO(page.screenshot())).convert("RGB"), ms))

    for _ in range(40):  # 10 s of live tracks at 4 frames a second
        grab(250)
        time.sleep(0.25)
    page.fill("#chat-input", QUESTION)
    page.press("#chat-input", "Enter")
    time.sleep(1.0)
    grab(1200)  # "Thinking..."
    page.wait_for_function(
        "() => [...document.querySelectorAll('#chat-log .msg.agent')]"
        ".some(m => !m.classList.contains('wait'))", timeout=180_000)
    for _ in range(12):  # the answer, with the map still moving
        grab(400)
        time.sleep(0.4)
    frames[-1] = (frames[-1][0], 3000)  # hold the last frame
    browser.close()

small = [(im.resize((960, int(im.height * 960 / im.width)), Image.LANCZOS), ms)
         for im, ms in frames]
# One palette for every frame, built with an octree so small coloured dots (the drone,
# the legend) keep their colour instead of being merged into the grey background.
sheet = Image.new("RGB", (small[0][0].width, small[0][0].height * 6))
for k, idx in enumerate(range(0, len(small), max(1, len(small) // 6))[:6]):
    sheet.paste(small[idx][0], (0, k * small[0][0].height))
palette = sheet.quantize(colors=255, method=Image.Quantize.FASTOCTREE)
pal = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im, _ in small]
pal[0].save(OUT, save_all=True, append_images=pal[1:], duration=[ms for _, ms in small],
            loop=0, optimize=True)
print("frames", len(frames))
