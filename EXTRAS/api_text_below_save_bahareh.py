from fastapi import FastAPI, File, Form, UploadFile # type: ignore
from fastapi.responses import StreamingResponse # type: ignore
from fastapi.middleware.cors import CORSMiddleware # type: ignore
from fastapi.staticfiles import StaticFiles # type: ignore
from fastapi import WebSocket, WebSocketDisconnect # type: ignore
from typing import List
from PIL import Image, ImageDraw, ImageFont, ImageWin # type: ignore
import win32print # type: ignore
import win32ui # type: ignore
import os
import tempfile
from datetime import datetime
import io
import qrcode # type: ignore

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

STATIC_DIR = "static"
os.makedirs(STATIC_DIR, exist_ok=True)
PRINTER_NAME = "M832"  # Replace with your printer's name

@app.post("/process-image")
async def process_image(image: UploadFile = File(...), text: str = Form(...)):
    try:
        contents = await image.read()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = os.path.splitext(image.filename)[0]
        orig_filename = f"{filename_base}_original_{timestamp}.png"
        edited_filename = f"{filename_base}_edited_{timestamp}.png"
        orig_path = os.path.join(STATIC_DIR, orig_filename)
        edited_path = os.path.join(STATIC_DIR, edited_filename)

        with open(orig_path, "wb") as f:
            f.write(contents)

        # Resize main image to target width
        img = Image.open(io.BytesIO(contents)).convert("RGB")
        target_width = 1280
        aspect_ratio = img.height / img.width
        target_height = int(target_width * aspect_ratio)
        img = img.resize((target_width, target_height), Image.Resampling.LANCZOS)

        # Date label box
        day_text = datetime.now().strftime("%Y-%m-%d %H:%M")
        padding = 13
        font_size = max(55, int(target_width / 32))
        try:
            font = ImageFont.truetype("font_for_printing.ttf", font_size)
        except:
            font = ImageFont.load_default()

        text_bbox = ImageDraw.Draw(Image.new("RGB", (1, 1))).textbbox((0, 0), day_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        box_img = Image.new("RGB", (text_width + 2 * padding, text_height + 3 * padding), "white")
        draw_box = ImageDraw.Draw(box_img)
        draw_box.text((padding, padding), day_text, fill="black", font=font)
        img.paste(box_img, (0, target_height - box_img.height))

        # Load assets
        qr_size = 250
        qr_path = os.path.join(STATIC_DIR, "qr_code.png")
        qr_img = Image.open(qr_path).convert("RGB").resize((qr_size, qr_size), Image.Resampling.LANCZOS)

        logo1_path = os.path.join(STATIC_DIR, "logo1.png")
        logo1_img = Image.open(logo1_path).convert("RGB")
        logo2_path = os.path.join(STATIC_DIR, "logo2.png")
        logo2_img = Image.open(logo2_path).convert("RGB")

        # Resize logos proportionally
        def resize_preserve_aspect(img):
            w, h = img.size
            new_width = int(qr_size * w / h)
            return img.resize((new_width, qr_size), Image.Resampling.LANCZOS)

        logo1_img = resize_preserve_aspect(logo1_img)
        logo2_img = resize_preserve_aspect(logo2_img)

        # Prepare footer
        total_height = qr_size
        footer_img = Image.new("RGB", (target_width, total_height), "white")
        current_x = padding
        footer_img.paste(logo1_img, (current_x, (total_height - qr_size) // 2))
        current_x += logo1_img.width + padding
        footer_img.paste(logo2_img, (current_x, (total_height - qr_size) // 2))
        qr_x = target_width - qr_size - padding
        footer_img.paste(qr_img, (qr_x, (total_height - qr_size) // 2))

        # Combine
        combined = Image.new("RGB", (target_width, target_height + footer_img.height), "white")
        combined.paste(img, (0, 0))
        combined.paste(footer_img, (0, target_height))
        combined.save(edited_path)

        # Silent print
        temp_path = os.path.join(tempfile.gettempdir(), f"temp_print_{timestamp}.png")
        combined.save(temp_path)

        try:
            hprinter = win32print.OpenPrinter(PRINTER_NAME)
            try:
                pdc = win32ui.CreateDC()
                pdc.CreatePrinterDC(PRINTER_NAME)
                pdc.StartDoc("Silent PNG Print")
                pdc.StartPage()
                printable_area = pdc.GetDeviceCaps(8), pdc.GetDeviceCaps(10)
                scale = min(printable_area[0] / combined.width, printable_area[1] / combined.height)
                dib = ImageWin.Dib(combined.resize(
                    (int(combined.width * scale), int(combined.height * scale))
                ))
                dib.draw(pdc.GetHandleOutput(), (0, 0,
                            int(combined.width * scale),
                            int(combined.height * scale)))
                pdc.EndPage()
                pdc.EndDoc()
                pdc.DeleteDC()
            finally:
                win32print.ClosePrinter(hprinter)
        finally:
            os.remove(temp_path)

        buf = io.BytesIO()
        combined.save(buf, format="PNG")
        buf.seek(0)
        return StreamingResponse(buf, media_type="image/png")

    except Exception as e:
        return {"error": str(e)}

@app.get("/generate-qr")
async def generate_qr():
    qr = qrcode.QRCode(version=1, box_size=10, border=4)
    qr.add_data("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    qr.make(fit=True)
    img = qr.make_image(fill="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# ------------------------
# WEBSOCKET LOGIC SECTION
# ------------------------

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
