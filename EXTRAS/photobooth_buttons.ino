const int button1Pin = 2;
const int button2Pin = 3;
const int button3Pin = 4;

void setup() {
  Serial.begin(9600);
  pinMode(button1Pin, INPUT_PULLUP);
  pinMode(button2Pin, INPUT_PULLUP);
  pinMode(button3Pin, INPUT_PULLUP);
}

void loop() {
  if (digitalRead(button1Pin) == LOW) {
    Serial.println("BUTTON_1");
    delay(300);
  }
  if (digitalRead(button2Pin) == LOW) {
    Serial.println("BUTTON_2");
    delay(300);
  }
  if (digitalRead(button3Pin) == LOW) {
    Serial.println("BUTTON_3");
    delay(300);
  }
}
