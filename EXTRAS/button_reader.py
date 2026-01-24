from gpiozero import Button
from signal import pause

# Setup buttons
button1 = Button(17)  # GPIO17
button2 = Button(27)  # GPIO27
button3 = Button(22)  # GPIO22

# Define actions
def handle_button1():
    print("Button 1 pressed! (grayscale)")
    # Call grayscale function

def handle_button2():
    print("Button 2 pressed! (dither)")
    # Call dither function

def handle_button3():
    print("Button 3 pressed! (fun)")
    # Call fun effect function

# Link button press events to functions
button1.when_pressed = handle_button1
button2.when_pressed = handle_button2
button3.when_pressed = handle_button3

print("Waiting for button presses...")
pause()
