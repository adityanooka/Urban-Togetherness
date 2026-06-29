"""
UrbanTogetherness Photobooth — Backend Server
=============================================
Runs on: Raspberry Pi 5 (Linux/macOS) and Windows PC
  - Linux/macOS : sends print jobs to the Phomemo M832 via CUPS (lp command)
  - Windows     : saves the composed image locally and opens a preview

Start with:
    fastapi dev server.py        # hot-reload (development)
    uvicorn server:app --port 8000  # stable (events/production)

Dependencies (install once):
    pip install fastapi "uvicorn[standard]" python-multipart Pillow numpy
"""

import asyncio
import os
import io
import glob
import random
import platform
from datetime import datetime

import numpy as np
from PIL import Image, ImageDraw, ImageFont
from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.responses import FileResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List

# ---------------------------------------------------------------------------
# App & middleware
# ---------------------------------------------------------------------------
app = FastAPI(title="UrbanTogetherness Photobooth")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Paths — absolute so the server works from any working directory
# ---------------------------------------------------------------------------
BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
PRINTS_DIR = os.path.join(STATIC_DIR, "prints")
os.makedirs(PRINTS_DIR, exist_ok=True)

CURRENT_OS   = platform.system()   # "Linux", "Darwin", or "Windows"
PRINTER_NAME = "M832"              # CUPS printer name on the Pi

# ---------------------------------------------------------------------------
# Print layout constants  (80 mm thermal roll @ 300 DPI)
# ---------------------------------------------------------------------------
PRINTER_DPI  = 300
MM_TO_PX     = PRINTER_DPI / 25.4          # 1 mm in pixels
PRINT_WIDTH  = int(80 * MM_TO_PX)          # 945 px  = full 80 mm roll width
PADDING      = 30                           # general gap between sections (px)
LOGO_HEIGHT  = 60                           # height of the top logo (px)
QUOTE_HEIGHT = 160                          # reserved height for quote block (px)

# Extra blank roll tail so paper feeds past the tear-bar.
# The anchor pixel (RGB 254,254,254) at the bottom edge is imperceptibly
# off-white but non-white, forcing the printer to advance all the way there.
# Increase this value if the paper still doesn't feed far enough.
TAIL_SPACE   = 300

# ---------------------------------------------------------------------------
# UX quotes printed on the footer (quote text, attribution)
# ---------------------------------------------------------------------------
USABILITY_QUOTES = [
    ("Users don't read, they scan.", "- Jakob Nielsen"),
    ("If the user can't use it, it doesn't work.", "- Susan Dray"),
    ("Design is how it works.", "- Steve Jobs"),
    ("People ignore design that ignores people.", "- Frank Chimero"),
    ("The best interface is no interface.", "- Golden Krishna"),
    ("Simplicity: subtract the obvious,\nadd the meaningful.", "- John Maeda"),
    ("You cannot understand good design\nwithout understanding people.", "- Dieter Rams"),
    ("Make things as simple as possible,\nbut no simpler.", "- Albert Einstein"),
    ("Form follows function.", "- Louis Sullivan"),
    ("Design is thinking made visual.", "- Saul Bass"),
    ("A UI is like a joke — if you have to explain it,\nit's not that good.", "- Martin LeBlanc"),
]

# ---------------------------------------------------------------------------
# WebSocket — relays button events from an optional Arduino bridge
# ---------------------------------------------------------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_frontend():
    """Serve index.html from the same directory as this file."""
    index_path = os.path.join(BASE_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    raise HTTPException(status_code=404, detail="index.html not found")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Relay messages between the browser and the Arduino button bridge."""
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/find_images")
async def find_images(people: str, category: str):
    """
    Return a single random image URL for the given people + category.
    Looks inside:  static/{Single|Couple|Group}{Memes|Poses|Cringe|Family}/
    """
    prefix      = {"single": "Single", "couple": "Couple", "group": "Group"}.get(people.lower(), "Single")
    full_folder = f"{prefix}{category.lower().capitalize()}"
    folder_path = os.path.join(STATIC_DIR, full_folder)

    if not os.path.exists(folder_path):
        return []

    images = (
        glob.glob(os.path.join(folder_path, "*.[jJ][pP][gG]")) +
        glob.glob(os.path.join(folder_path, "*.[pP][nN][gG]"))
    )
    if not images:
        return []

    chosen = random.choice(images)
    return [f"/static/{full_folder}/{os.path.basename(chosen)}"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a .ttf from static/; fall back to PIL's built-in default."""
    try:
        return ImageFont.truetype(os.path.join(STATIC_DIR, filename), size)
    except IOError:
        return ImageFont.load_default()


def _apply_bcsh(
    img: Image.Image,
    brightness: float,
    contrast: float,
    shadows: float,
    highlights: float,
) -> Image.Image:
    """
    Apply Brightness / Contrast / Shadows / Highlights in one NumPy pass.

    This replicates the JavaScript preview math pixel-for-pixel so the
    physical print matches the on-screen preview exactly.  Using NumPy
    instead of a Python pixel loop cuts processing time from ~5–10 s to
    under 0.1 s on a Raspberry Pi 5.

    Parameter scale: the frontend sends values on a 0–2 float scale where
    1.0 = neutral (no change).
    """
    arr = np.array(img, dtype=np.float32)

    # 1. Brightness — additive delta (frontend scale: 0–2, neutral = 1.0)
    arr += (brightness * 100.0) - 100.0

    # 2. Contrast — multiplicative around mid-grey (128)
    arr = (arr - 128.0) * contrast + 128.0

    # 3. Shadows / Highlights — blend factor derived from per-pixel luminance
    luminance = arr.mean(axis=2, keepdims=True) / 255.0
    luminance  = np.clip(luminance, 0.0, 1.0)
    arr *= shadows * (1.0 - luminance) + highlights * luminance

    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


# ---------------------------------------------------------------------------
# Main endpoint: receive photo → compose layout → save → print → return PNG
# ---------------------------------------------------------------------------

@app.post("/process-image")
async def process_image(
    image:      UploadFile = File(...),
    brightness: float      = Form(1.0),
    contrast:   float      = Form(1.0),
    shadows:    float      = Form(1.0),
    highlights: float      = Form(1.0),
    copies:     int        = Form(1),
):
    """
    Receives the JPEG capture from the browser, builds the full print strip,
    saves it to static/prints/, sends it to CUPS (Linux) or opens a preview
    (Windows), then returns the composed PNG so the browser can show it.
    """
    try:
        # 1. Decode and mirror (webcam image is flipped relative to preview)
        img = Image.open(io.BytesIO(await image.read())).convert("RGB")
        img = img.transpose(Image.FLIP_LEFT_RIGHT)

        # 2. Apply BCSH adjustments via NumPy (fast, matches JS preview)
        img = _apply_bcsh(img, brightness, contrast, shadows, highlights)

        # 3. Scale to 80 mm print width, preserving aspect ratio
        target_h = int(PRINT_WIDTH * img.height / img.width)
        img = img.resize((PRINT_WIDTH, target_h), Image.Resampling.LANCZOS)

        # 4. Load optional HCI logo
        logo      = None
        logo_path = os.path.join(STATIC_DIR, "HCI_Logo.png")
        if os.path.exists(logo_path):
            raw_logo = Image.open(logo_path).convert("RGBA")
            logo_w   = int(LOGO_HEIGHT * raw_logo.width / raw_logo.height)
            logo     = raw_logo.resize((logo_w, LOGO_HEIGHT), Image.Resampling.LANCZOS)

        logo_section  = LOGO_HEIGHT if logo else 0
        canvas_height = logo_section + PADDING + target_h + PADDING + QUOTE_HEIGHT + PADDING + TAIL_SPACE

        # 5. Build the print canvas (white background)
        canvas = Image.new("RGB", (PRINT_WIDTH, canvas_height), "white")
        draw   = ImageDraw.Draw(canvas)
        y      = 0

        # — Logo —
        if logo:
            canvas.paste(logo, (PADDING, y), logo)
        y += logo_section + PADDING

        # — Title —
        title_font = _load_font("font_for_printing.ttf", 40)
        title      = "UrbanTogetherness Photobooth"
        tbbox      = draw.textbbox((0, 0), title, font=title_font)
        draw.text(((PRINT_WIDTH - (tbbox[2] - tbbox[0])) // 2, y), title, fill="black", font=title_font)
        y += tbbox[3] - tbbox[1] + PADDING // 2

        # — Photo —
        canvas.paste(img, (0, y))

        # — Datetime box (bottom-left corner of photo) —
        date_font = _load_font("font_for_printing.ttf", 28)
        date_str  = datetime.now().strftime("%Y-%m-%d %H:%M")
        dbbox     = draw.textbbox((0, 0), date_str, font=date_font)
        bw        = dbbox[2] - dbbox[0] + 20
        bh        = dbbox[3] - dbbox[1] + 20
        date_box  = Image.new("RGB", (bw, bh), "white")
        db_draw   = ImageDraw.Draw(date_box)
        db_draw.rectangle((0, 0, bw - 1, bh - 1), outline="black", width=2)
        db_draw.text((10, 8), date_str, fill="black", font=date_font)
        canvas.paste(date_box, (10, y + target_h - bh - 10))
        y += target_h + PADDING

        # — Random UX quote + author —
        quote, author = random.choice(USABILITY_QUOTES)
        font_size     = 30
        q_font        = _load_font("font_for_printing.ttf", font_size)
        qbbox         = draw.textbbox((0, 0), quote,  font=q_font)
        abbox         = draw.textbbox((0, 0), author, font=q_font)
        # Shrink font until both lines fit within the printable width
        while (qbbox[2] > PRINT_WIDTH - 2 * PADDING or abbox[2] > PRINT_WIDTH - 2 * PADDING) and font_size > 10:
            font_size -= 1
            q_font = _load_font("font_for_printing.ttf", font_size)
            qbbox  = draw.textbbox((0, 0), quote,  font=q_font)
            abbox  = draw.textbbox((0, 0), author, font=q_font)

        draw.text(((PRINT_WIDTH - qbbox[2]) // 2, y), quote, fill="black", font=q_font)
        line_h = qbbox[3] + 10
        draw.text(((PRINT_WIDTH * 3 // 4) - abbox[2] // 2, y + line_h), author, fill="black", font=q_font)

        # — Hashtag (bottom right) —
        h_font = _load_font("font_for_printing.ttf", 36)
        h_text = "#ECSCW2026"
        h_text = " "
        hbbox  = draw.textbbox((0, 0), h_text, font=h_font)
        y     += line_h + abbox[3] + 40
        draw.text((PRINT_WIDTH - hbbox[2] - PADDING, y), h_text, fill="black", font=h_font)

        # — Anchor pixel: RGB(254,254,254) is indistinguishable to the eye but
        #   registers as non-white content, forcing the thermal printer to advance
        #   paper all the way to the bottom of the canvas (past the tear-bar). —
        draw.point((PRINT_WIDTH - 1, canvas_height - 1), fill=(254, 254, 254))

        # 6. Save local archive copy
        timestamp  = datetime.now().strftime("%Y%m%d_%H%M%S")
        print_path = os.path.join(PRINTS_DIR, f"print_{timestamp}.png")
        buf        = io.BytesIO()
        canvas.save(buf, format="PNG")
        buf.seek(0)
        with open(print_path, "wb") as f:
            f.write(buf.getvalue())

        # 7. Send to printer
        if CURRENT_OS in ("Linux", "Darwin"):
            #
            # CUPS lp options explained:
            #   scaling=100        — print at the image's actual DPI, no CUPS rescaling
            #   media=Custom…      — declare the page as a continuous roll strip;
            #                        height is computed from the actual canvas so CUPS
            #                        doesn't pad to a fixed page size
            #   page-*=0           — zero all four page margins in the CUPS filter
            #
            # If the printer still adds a top margin after all these options, the
            # most likely cause is the PPD's ImageableArea entry.  In that case,
            # run  lpoptions -p M832  to inspect the queue and adjust the PPD, or
            # increase INITIAL_PADDING in the layout constants above to compensate.
            #
            canvas_h_mm   = round(canvas_height / MM_TO_PX, 1)
            media_size    = f"Custom.80mmx{canvas_h_mm + 5}mm"   # +5 mm buffer

            process = await asyncio.create_subprocess_exec(
                "lp",
                "-d", PRINTER_NAME,
                "-n", str(copies),
                "-o", "scaling=100",        # no CUPS rescaling
                "-o", f"media={media_size}",
                "-o", "page-left=0",
                "-o", "page-right=0",
                "-o", "page-top=0",
                "-o", "page-bottom=0",
                print_path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await process.communicate()
            if process.returncode != 0:
                raise HTTPException(status_code=500, detail=f"CUPS error: {stderr.decode()}")
            print(f"Queued {copies}x: {stdout.decode().strip()}")

        elif CURRENT_OS == "Windows":
            # Windows: no physical print.  The composed image is saved above.
            # To enable real Windows printing, add a win32print block here.
            print(f"[Windows] Layout saved to: {print_path}")
            try:
                os.startfile(print_path)    # opens in default image viewer
            except Exception:
                pass

        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")

    except HTTPException:
        raise
    except Exception as e:
        print(f"process_image error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


# Static files are mounted AFTER all routes so they don't shadow any endpoint.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
