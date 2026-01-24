from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List
from PIL import Image, ImageDraw, ImageFont, ImageEnhance, ImageWin
import win32print
import win32ui
import os
import tempfile
from datetime import datetime
import io
import qrcode
import glob
import random

# Initialize FastAPI application
app = FastAPI()

# Add CORS middleware to allow cross-origin requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Define project root directory (user must update this path)
PROJECT_ROOT = "C:\\Users\\adity\\Desktop\\photo-booth"

# Construct path to static folder for images and assets
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

# Ensure static directory exists
os.makedirs(STATIC_DIR, exist_ok=True)

# Printer name for M832 thermal printer
PRINTER_NAME = "M832"

# Mount static directory to serve files (images, CSS, JS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Usability/UX quotes with attribution (centered, quote above, name below)
USABILITY_QUOTES = [
    ("Users don’t read, they scan.", "– Jakob Nielsen"),
    ("If the user can’t use it, it doesn’t work.", "– Susan Dray"),
    ("Design is not just what it looks like and feels like. Design is how it works.", "– Steve Jobs"),
    ("People ignore design that ignores people.", "– Frank Chimero"),
    ("Good design is like a refrigerator—when it works, no one notices.", "– Don Norman"),
    ("The best interface is no interface.", "– Golden Krishna"),
    ("Simplicity is about subtracting the obvious and adding the meaningful.", "– John Maeda"),
    ("You cannot understand good design if you do not understand people.", "– Dieter Rams"),
    ("Make things as simple as possible, but no simpler.", "– Albert Einstein"),
    ("Form follows function.", "– Louis Sullivan"),
    ("Usability is about people and how they understand and use things, not about technology.", "– Steve Krug"),
    ("Design is thinking made visual.", "– Saul Bass"),
    ("The function of design is letting design function.", "– Micha Commeren"),
    ("A user interface is like a joke. If you have to explain it, it’s not that good.", "– Martin LeBlanc")
]


# WebSocket connection manager for real-time communication
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

# WebSocket endpoint for Arduino bridge communication
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            print(f"Received from client/bridge: {data}")
            await manager.broadcast(data)
    except WebSocketDisconnect:
        manager.disconnect(websocket)

# Endpoint to find random images based on people and category
@app.get("/find_images")
async def find_images(people: str, category: str):
    search_term = f"{people}{category}".lower()
    print(f"Searching for images with term: '{search_term}' in '{STATIC_DIR}'")
    try:
        all_static_files = glob.glob(os.path.join(STATIC_DIR, "*.*"))
        matching_images = [
            f"/static/{os.path.basename(file_path)}"
            for file_path in all_static_files
            if search_term in os.path.splitext(os.path.basename(file_path))[0].lower()
            and os.path.splitext(file_path)[1].lower() in [".jpg", ".jpeg", ".png"]
        ]
        if not matching_images:
            print(f"!!! No images found for search term '{search_term}'.")
            return JSONResponse(content=[], status_code=200)
        print(f"Found matching images: {matching_images}")
        return JSONResponse(content=matching_images)
    except Exception as e:
        print(f"Error finding images: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)

# Endpoint to process and print uploaded image
@app.post("/process-image")
async def process_image(image: UploadFile = File(...), text: str = Form(...), brightness: float = Form(1.0), contrast: float = Form(1.0), shadows: float = Form(1.0), highlights: float = Form(1.0)):
    try:
        contents = await image.read()
        img = Image.open(io.BytesIO(contents)).convert("RGB")
        img = img.transpose(Image.FLIP_LEFT_RIGHT)

        # ########################################################################## #
        # ### START: FIX FOR IMAGE PROCESSING MISMATCH                           ### #
        # ########################################################################## #
        # This new logic exactly matches the JavaScript preview logic.
        
        # Convert received factors (like 1.85) into the values the JS logic uses
        brightness_delta = (brightness * 100) - 100
        contrast_factor = contrast
        shadows_factor = shadows
        highlights_factor = highlights

        img_data = img.load()
        for y in range(img.height):
            for x in range(img.width):
                r, g, b = img_data[x, y]
                
                # Use floats for intermediate calculations to maintain precision
                _r, _g, _b = float(r), float(g), float(b)

                # 1. Apply Brightness (Additive)
                _r += brightness_delta
                _g += brightness_delta
                _b += brightness_delta

                # 2. Apply Contrast (Multiplicative around midpoint 128)
                _r = (_r - 128.0) * contrast_factor + 128.0
                _g = (_g - 128.0) * contrast_factor + 128.0
                _b = (_b - 128.0) * contrast_factor + 128.0

                # 3. Apply Shadows & Highlights
                # Calculate blend factor based on pixel luminance
                blend_factor = ((_r + _g + _b) / 3.0) / 255.0
                blend_factor = max(0.0, min(1.0, blend_factor)) # Clamp to avoid errors
                
                final_factor = shadows_factor * (1.0 - blend_factor) + highlights_factor * blend_factor
                _r *= final_factor
                _g *= final_factor
                _b *= final_factor

                # Clamp final values and assign back to the image
                img_data[x, y] = (
                    max(0, min(255, int(_r))),
                    max(0, min(255, int(_g))),
                    max(0, min(255, int(_b)))
                )

        # ########################################################################## #
        # ### END: FIX FOR IMAGE PROCESSING MISMATCH                             ### #
        # ########################################################################## #

        # Resize main image to fit full 80mm width (945 pixels at 300 DPI)
        PRINTER_DPI = 300
        MM_TO_PIXELS = PRINTER_DPI / 25.4
        target_width = int(80 * MM_TO_PIXELS)
        aspect_ratio = img.height / img.width
        target_height = int(target_width * aspect_ratio)
        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

        # Top logos
        TOP_LOGO_HEIGHT = 60
        logo_left_path = os.path.join(STATIC_DIR, "HCI_Logo.png")
        
        logo_left_img = Image.open(logo_left_path).convert("RGBA") if os.path.exists(logo_left_path) else None

        if logo_left_img:
            l_aspect = logo_left_img.width / logo_left_img.height
            logo_left_img = logo_left_img.resize((int(TOP_LOGO_HEIGHT * l_aspect), TOP_LOGO_HEIGHT), Image.Resampling.LANCZOS)

        # Define layout constants
        PADDING = 30
        INITIAL_PADDING = 0
        TOP_SECTION_HEIGHT = TOP_LOGO_HEIGHT if logo_left_img else 0
        QUOTE_SECTION_HEIGHT = 150
        BOTTOM_SECTION_HEIGHT = 0
        
        EXTRA_BOTTOM_WHITE_SPACE = 100

        final_img_height = (INITIAL_PADDING + TOP_SECTION_HEIGHT + PADDING + 
                            target_height + PADDING + 
                            QUOTE_SECTION_HEIGHT + PADDING + 
                            BOTTOM_SECTION_HEIGHT + PADDING + 
                            EXTRA_BOTTOM_WHITE_SPACE)
                            
        final_img = Image.new("RGB", (target_width, final_img_height), (255, 255, 255))
        draw = ImageDraw.Draw(final_img)
        
        current_y = INITIAL_PADDING

        # Paste top logos
        if logo_left_img:
            final_img.paste(logo_left_img, (PADDING, current_y), logo_left_img)
        current_y += TOP_SECTION_HEIGHT + PADDING

        # Add "UrbanTogetherness Photobooth" text, center-aligned
        def load_font(path, size):
            try: return ImageFont.truetype(os.path.join(STATIC_DIR, path), size)
            except IOError: return ImageFont.load_default()
        
        title_font = load_font("font_for_printing.ttf", 40)
        title_text = "UrbanTogetherness Photobooth"
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = (target_width - title_width) // 2
        draw.text((title_x, current_y), title_text, fill="black", font=title_font)
        current_y += title_bbox[3] - title_bbox[1] + (PADDING // 2)

        # Paste main image
        final_img.paste(img, (0, current_y))
        
        # Add date box to main image
        date_font = load_font("font_for_printing.ttf", 28)
        date_text = datetime.now().strftime("%Y-%m-%d %H:%M")
        date_bbox = draw.textbbox((0, 0), date_text, font=date_font)
        date_box_width = date_bbox[2] - date_bbox[0] + 20
        date_box_height = date_bbox[3] - date_bbox[1] + 20
        date_box_img = Image.new("RGB", (date_box_width, date_box_height), "white")
        ImageDraw.Draw(date_box_img).rectangle((0, 0, date_box_width-1, date_box_height-1), outline="black", width=2)
        ImageDraw.Draw(date_box_img).text((10, 8), date_text, fill="black", font=date_font)
        final_img.paste(date_box_img, (10, current_y + target_height - date_box_height - 10))
        
        current_y += target_height + PADDING

        # Random Usability Quote with Attribution (centered, quote above, name below)
        quote, author = random.choice(USABILITY_QUOTES)
        font_size = 30
        quote_font = load_font("font_for_printing.ttf", font_size)

        quote_bbox = draw.textbbox((0, 0), quote, font=quote_font)
        author_bbox = draw.textbbox((0, 0), author, font=quote_font)
        
        while (quote_bbox[2] > target_width - 2*PADDING or author_bbox[2] > target_width - 2*PADDING) and font_size > 10:
            font_size -= 1
            quote_font = load_font("font_for_printing.ttf", font_size)
            quote_bbox = draw.textbbox((0, 0), quote, font=quote_font)
            author_bbox = draw.textbbox((0, 0), author, font=quote_font)

        quote_x = (target_width - quote_bbox[2]) // 2
        author_x = (target_width * 3 // 4) - (author_bbox[2] // 2)
        line_height = quote_bbox[3] + 10
        
        draw.text((quote_x, current_y), quote, fill="black", font=quote_font)
        draw.text((author_x, current_y + line_height), author, fill="black", font=quote_font)

        current_y += QUOTE_SECTION_HEIGHT + PADDING

        # Add #WorldUsabilityDay2025 in bottom-right corner
        hashtag_font = load_font("font_for_printing.ttf", 36)
        hashtag_text = "#WorldUsabilityDay2025"
        hashtag_bbox = draw.textbbox((0, 0), hashtag_text, font=hashtag_font)
        hashtag_x = target_width - hashtag_bbox[2] - PADDING
        hashtag_y = final_img.height - hashtag_bbox[3] - PADDING - 20  # Above extra white space
        draw.text((hashtag_x, hashtag_y), hashtag_text, fill="black", font=hashtag_font)

        # Save the full-color final image to the static folder for archiving
        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"photobooth_{timestamp}.jpg"
            save_path = os.path.join(STATIC_DIR, filename)
            final_img.save(save_path, "JPEG", quality=95)
            print(f"Successfully saved archive image to: {save_path}")
        except Exception as e:
            print(f"Error saving image: {e}")
        
        # ########################################################################## #
        # ### START: FINAL PRINTING BLOCK                                        ### #
        # ########################################################################## #
        
        try:
            hprinter = win32print.OpenPrinter(PRINTER_NAME)
            try:
                pdc = win32ui.CreateDC()
                pdc.CreatePrinterDC(PRINTER_NAME)
                pdc.StartDoc("Photo Booth Print")
                pdc.StartPage()

                dib = ImageWin.Dib(final_img)
                destination_rect = (0, 0, final_img.width, final_img.height)
                dib.draw(pdc.GetHandleOutput(), destination_rect)
                
                pdc.EndPage()
                pdc.EndDoc()
                pdc.DeleteDC()
                print("Successfully sent RGB image to printer")
            finally:
                win32print.ClosePrinter(hprinter)
        except Exception as e:
            print(f"Printing error: {e}")

        # ######################################################################## #
        # ### END: FINAL PRINTING BLOCK                                        ### #
        # ######################################################################## #
        
        buf = io.BytesIO()
        final_img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")

    except Exception as e:
        print(f"Process image error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)