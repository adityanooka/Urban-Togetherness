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
PROJECT_ROOT = "C:\\Users\\BAHAR\\Desktop\\photo-booth"

# Construct path to static folder for images and assets
STATIC_DIR = os.path.join(PROJECT_ROOT, "static")

# Ensure static directory exists
os.makedirs(STATIC_DIR, exist_ok=True)

# Printer name for M832 thermal printer
PRINTER_NAME = "M832"

# Mount static directory to serve files (images, CSS, JS)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

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
    """
    Finds random images in the 'static' folder matching the selected people and category.
    """
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


# Helper function to generate QR code image
def generate_qr_image(data: str, size: int = 200) -> Image.Image:
    """Generates a QR code PIL Image with no border."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=0,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size, size), Image.Resampling.LANCZOS)

# Endpoint to process and print uploaded image
@app.post("/process-image")
async def process_image(image: UploadFile = File(...), text: str = Form(...), brightness: float = Form(1.0), contrast: float = Form(1.0), shadows: float = Form(1.0), highlights: float = Form(1.0)):
    try:
        # Read uploaded image data
        contents = await image.read()
        
        # Load and process image
        img = Image.open(io.BytesIO(contents)).convert("RGB")
        
        # Change: Removed the horizontal flip. The frontend now sends the correctly oriented image.
        # img = img.transpose(Image.FLIP_LEFT_RIGHT)

        # Apply brightness adjustment
        enhancer_brightness = ImageEnhance.Brightness(img)
        img = enhancer_brightness.enhance(brightness)
        
        # Apply contrast adjustment
        enhancer_contrast = ImageEnhance.Contrast(img)
        img = enhancer_contrast.enhance(contrast)
        
        # Apply shadows and highlights adjustments pixel-by-pixel if needed (can be slow)
        # Note: These are simplified adjustments. For better results, consider more advanced algorithms.
        if shadows != 1.0 or highlights != 1.0:
            img_data = img.load()
            for x in range(img.width):
                for y in range(img.height):
                    r, g, b = img_data[x, y]
                    # Simple shadow/highlight logic
                    factor = highlights if (r + g + b) / 3 > 128 else shadows
                    r = min(255, int(r * factor))
                    g = min(255, int(g * factor))
                    b = min(255, int(b * factor))
                    img_data[x, y] = (r, g, b)

        # Resize image to fit full 80mm width (945 pixels at 300 DPI)
        PRINTER_DPI = 300
        MM_TO_PIXELS = PRINTER_DPI / 25.4
        target_width = int(80 * MM_TO_PIXELS)
        aspect_ratio = img.height / img.width
        target_height = int(target_width * aspect_ratio)
        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

        # Load HCI logo
        logo_path = os.path.join(STATIC_DIR, "HCI_Logo.png")
        logo_img = Image.open(logo_path).convert("RGBA") if os.path.exists(logo_path) else None
        
        if logo_img:
            logo_aspect = logo_img.height / logo_img.width
            logo_width = 400
            logo_img = logo_img.resize((logo_width, int(logo_width * logo_aspect)), Image.Resampling.LANCZOS)

        # Define layout constants
        logo_height = logo_img.height if logo_img else 50
        TITLE_HEIGHT = 80
        WHITE_SPACE_HEIGHT = 250
        FOOTER_HEIGHT = 200
        PADDING = 20

        final_img_height = PADDING + logo_height + PADDING + TITLE_HEIGHT + target_height + WHITE_SPACE_HEIGHT + FOOTER_HEIGHT + PADDING
        final_img = Image.new("RGB", (target_width, final_img_height), (255, 255, 255))
        draw = ImageDraw.Draw(final_img)

        # Paste logo
        current_y = PADDING
        if logo_img:
            final_img.paste(logo_img, (PADDING, current_y), logo_img)
            current_y += logo_img.height + PADDING

        # Add title text
        def load_font(size):
            try: return ImageFont.truetype(os.path.join(STATIC_DIR, "font_for_printing.ttf"), size)
            except: return ImageFont.load_default()

        title_font = load_font(40)
        title_text = "Urban Togetherness Photobooth"
        title_bbox = draw.textbbox((0,0), title_text, font=title_font)
        draw.text(((target_width - (title_bbox[2]-title_bbox[0])) // 2, current_y), title_text, fill="black", font=title_font)
        current_y += TITLE_HEIGHT

        # Paste main image
        final_img.paste(img, (0, current_y))

        # Add date box
        date_font = load_font(28)
        date_text = datetime.now().strftime("%Y-%m-%d %H:%M")
        date_bbox = draw.textbbox((0, 0), date_text, font=date_font)
        date_box_img = Image.new("RGB", (date_bbox[2] + 20, date_bbox[3] + 20), "white")
        ImageDraw.Draw(date_box_img).rectangle((0, 0, date_box_img.width-1, date_box_img.height-1), outline="black", width=2)
        ImageDraw.Draw(date_box_img).text((10, 10), date_text, fill="black", font=date_font)
        final_img.paste(date_box_img, (10, current_y + target_height - date_box_img.height - 10))
        
        current_y += target_height + WHITE_SPACE_HEIGHT

        # Change: Corrected the QR code data link
        qr_data = "https://www.soscisurvey.de/UrbanTogetherness/"
        qr_img = generate_qr_image(qr_data, size=200)

        # Paste QR code and footer text
        qr_x_right = target_width - qr_img.width - PADDING
        final_img.paste(qr_img, (qr_x_right, current_y))

        footer_font = load_font(33)
        footer_text = "    Frame the Future Booth!"
        footer_bbox = draw.textbbox((0, 0), footer_text, font=footer_font)
        draw.text(((qr_x_right - (footer_bbox[2]-footer_bbox[0])) // 2, current_y + (qr_img.height - (footer_bbox[3]-footer_bbox[1])) // 2), footer_text, fill="black", font=footer_font)

        # Print the final image
        try:
            hprinter = win32print.OpenPrinter(PRINTER_NAME)
            try:
                dib = ImageWin.Dib(final_img)
                pdc = win32ui.CreateDC()
                pdc.CreatePrinterDC(PRINTER_NAME)
                pdc.StartDoc("Photo Booth Print")
                pdc.StartPage()
                dib.draw(pdc.GetHandleOutput(), (0, 0, pdc.GetDeviceCaps(8), pdc.GetDeviceCaps(10)))
                pdc.EndPage()
                pdc.EndDoc()
                pdc.DeleteDC()
                print("Successfully printed image")
            finally:
                win32print.ClosePrinter(hprinter)
        except Exception as e:
            print(f"Printing error: {e}")
            # This part should not raise an error to the client, just log it
        
        # Return the final image in the response
        buf = io.BytesIO()
        final_img.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")

    except Exception as e:
        print(f"Process image error: {e}")
        return JSONResponse(content={"error": str(e)}, status_code=500)