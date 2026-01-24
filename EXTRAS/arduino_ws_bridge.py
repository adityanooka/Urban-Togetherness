import serial
import asyncio
import websockets

SERIAL_PORT = "COM11"   # replace with yours
BAUDRATE = 9600
WEBSOCKET_URI = "ws://127.0.0.1:8000/ws"

FIRST_STEP_MAPPING = {
    "BUTTON_1": "single",
    "BUTTON_2": "couple",
    "BUTTON_3": "group",
}

SECOND_STEP_MAPPING = {
    "BUTTON_1": "memes",
    "BUTTON_2": "poses",
    "BUTTON_3": "cringe",
}

THIRD_STEP_MAPPING = {
    "BUTTON_1": "goBack",
    "BUTTON_2": "retake",
    "BUTTON_3": "continueToPrint",
}

async def main():
    step = 1
    ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
    print(f"Connected to serial: {SERIAL_PORT}")

    while True:
        try:
            print("Connecting WebSocket…")
            async with websockets.connect(WEBSOCKET_URI) as websocket:
                print("WebSocket connected.")

                while True:
                    if ser.in_waiting:
                        line = ser.readline().decode().strip()
                        if not line:
                            continue
                        print("From Arduino:", line)

                        if step == 1:
                            if line in FIRST_STEP_MAPPING:
                                msg = f"PEOPLE:{FIRST_STEP_MAPPING[line]}"
                                await websocket.send(msg)
                                print("→ Sent to frontend:", msg)
                                step = 2

                        elif step == 2:
                            if line in SECOND_STEP_MAPPING:
                                msg = f"CATEGORY:{SECOND_STEP_MAPPING[line]}"
                                await websocket.send(msg)
                                print("→ Sent to frontend:", msg)
                                step = 3

                        elif step == 3:
                            if line in THIRD_STEP_MAPPING:
                                msg = THIRD_STEP_MAPPING[line]
                                await websocket.send(msg)
                                print("→ Sent to frontend:", msg)
                                step = 1

                    await asyncio.sleep(0.05)

        except Exception as e:
            print("WebSocket connection error:", e)
            print("Retrying in 3 seconds…")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())
