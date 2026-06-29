# UrbanTogetherness Photobooth

An interactive, standalone public photobooth installation designed to encourage social connection in urban and public spaces through embodied pose recreation. Developed at Bauhaus-Universität Weimar for the ECSCW 2026 conference. 

Users select a category (Memes, Poses, Family, Kids, or Cringe), recreate the displayed image together, apply custom visual tweaks (brightness, contrast, shadows, highlights), and receive an instant physical thermal print.

## Features
* **Cross-Platform Execution:** Automatically detects the operating system. Runs simulated testing outputs on Windows, and executes physical hardware prints on Linux/Raspberry Pi.
* **Hardware Integration:** Directly communicates with the Phomemo M832 thermal printer via CUPS, utilizing dynamic media sizing and 1-bit thresholding to bypass standard print margins.
* **High-Speed Image Processing:** Utilizes NumPy arrays for rapid, C-compiled pixel manipulation, reducing image rendering latency from seconds to milliseconds on single-board computers.
* **Offline Fallback:** Fonts and assets are hosted locally to ensure zero UI latency if the kiosk loses Wi-Fi connectivity.
* **Asynchronous Group Printing:** Single-request architecture allows the backend to handle multiple copy requests natively through the hardware spooler without freezing the server.

## Tech Stack
* **Frontend:** Vanilla HTML5, CSS3 (Glassmorphism UI), JavaScript
* **Backend:** Python 3, FastAPI, Uvicorn
* **Image Processing:** Pillow (PIL), NumPy
* **Hardware System:** Raspberry Pi 5, CUPS (Common UNIX Printing System)

## Installation & Setup

### 1. System Requirements
* Python 3.11+
* A USB Webcam
* (For Pi Deployment) Phomemo M832 Thermal Printer & CUPS Linux Drivers

### 2. Install Dependencies
Clone the repository, navigate to the project folder, and create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
