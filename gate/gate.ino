#include <Servo.h>

// Pin Definitions
const int trigPin = 2;
const int echoPin = 3;
const int redLED = 4;
const int blueLED = 5;
const int servoPin = 6;
const int gndPin1 = 7;
const int gndPin2 = 8;
const int buzzer = 11;

// Globals
Servo gateServo;
char command = ' ';
unsigned long lastDistanceTime = 0;
// Blinking state for '1' command
bool blinkState = false;
unsigned long lastBlinkTime = 0;
const unsigned long blinkInterval = 250;

void setup() {
  Serial.begin(9600);
  // Pin Modes
  pinMode(trigPin, OUTPUT);
  pinMode(echoPin, INPUT);
  pinMode(redLED, OUTPUT);
  pinMode(blueLED, OUTPUT);
  pinMode(buzzer, OUTPUT);
  pinMode(gndPin1, OUTPUT);
  pinMode(gndPin2, OUTPUT);
  // Set hardcoded ground pins LOW
  digitalWrite(gndPin1, LOW);
  digitalWrite(gndPin2, LOW);
  // Attach servo and set to 0°
  gateServo.attach(servoPin);
  gateServo.write(0);
  // Startup blinking and beeping
  startupBlink();
  Serial.println("[INIT] Arduino setup complete");
}

void loop() {
  handleSerialCommands();
  if (command == '1') {
    handleBlinking();  // Blink blue LED and beep buzzer
  } else {
    stopBlinking();    // Ensure they are off
    // Distance reading (every 50ms)
    unsigned long currentTime = millis();
    if (currentTime - lastDistanceTime >= 50) {
      float distance = getDistance();
      Serial.println(distance, 2);  // Print with 2 decimals
      lastDistanceTime = currentTime;
    }
  }
}

// --------------------- Modules ---------------------
void startupBlink() {
  Serial.println("[STARTUP] Starting buzzer and LED test");
  for (int i = 0; i < 5; i++) {
    digitalWrite(redLED, HIGH);
    digitalWrite(blueLED, HIGH);
    tone(buzzer, 1000); // 1000Hz for passive buzzer
    // For active buzzer, uncomment: digitalWrite(buzzer, HIGH);
    delay(150);
    digitalWrite(redLED, LOW);
    digitalWrite(blueLED, LOW);
    noTone(buzzer); // Stop tone for passive buzzer
    // For active buzzer, uncomment: digitalWrite(buzzer, LOW);
    delay(150);
  }
  Serial.println("[STARTUP] Test complete");
}

float getDistance() {
  digitalWrite(trigPin, LOW);
  delayMicroseconds(2);
  digitalWrite(trigPin, HIGH);
  delayMicroseconds(10);
  digitalWrite(trigPin, LOW);
  long duration = pulseIn(echoPin, HIGH, 25000);  // 25ms timeout
  if (duration == 0) return 9999.99;              // No echo = out of range
  float distance = duration * 0.0343 / 2.0;
  return distance;
}

void handleSerialCommands() {
  if (Serial.available()) {
    command = Serial.read();
    Serial.print("[CMD] Received: ");
    Serial.println(command);
    if (command == '1') {
      gateServo.write(180);  // Open
      Serial.println("[SERVO] Gate opened (180°)");
    }
    else if (command == '0') {
      gateServo.write(0);    // Close
      Serial.println("[SERVO] Gate closed (0°)");
    }
    else if (command == '2') {
      Serial.println("[BUZZER] Activating red LED and buzzer");
      blinkRedAndBuzzer(3);
      Serial.println("[BUZZER] Sequence complete");
    }
  }
}

void blinkRedAndBuzzer(int times) {
  for (int i = 0; i < times; i++) {
    digitalWrite(redLED, HIGH);
    tone(buzzer, 1000); // 1000Hz for passive buzzer
    // For active buzzer, uncomment: digitalWrite(buzzer, HIGH);
    Serial.println("[BUZZER] ON");
    delay(250);
    digitalWrite(redLED, LOW);
    noTone(buzzer); // Stop tone for passive buzzer
    // For active buzzer, uncomment: digitalWrite(buzzer, LOW);
    Serial.println("[BUZZER] OFF");
    delay(250);
  }
}

void handleBlinking() {
  unsigned long currentMillis = millis();
  if (currentMillis - lastBlinkTime >= blinkInterval) {
    blinkState = !blinkState;
    digitalWrite(blueLED, blinkState);
    if (blinkState) {
      tone(buzzer, 1000); // 1000Hz for passive buzzer
      // For active buzzer, uncomment: digitalWrite(buzzer, HIGH);
      Serial.println("[BUZZER] ON (blink)");
    } else {
      noTone(buzzer); // Stop tone for passive buzzer
      // For active buzzer, uncomment: digitalWrite(buzzer, LOW);
      Serial.println("[BUZZER] OFF (blink)");
    }
    lastBlinkTime = currentMillis;
  }
}

void stopBlinking() {
  digitalWrite(blueLED, LOW);
  noTone(buzzer); // Stop tone for passive buzzer
  // For active buzzer, uncomment: digitalWrite(buzzer, LOW);
  Serial.println("[BUZZER] Stopped");
}