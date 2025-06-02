#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 9
#define SS_PIN 10

MFRC522 mfrc522(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;
MFRC522::StatusCode card_status;

void setup() {
  Serial.begin(9600);
  while (!Serial);
  SPI.begin();
  mfrc522.PCD_Init();
  for (byte i = 0; i < 6; i++) {
    key.keyByte[i] = 0xFF;
  }
  Serial.println(F("==== CARD REGISTRATION ===="));
  Serial.println(F("Place your RFID card near the reader..."));
}

void loop() {
  if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) return;

  Serial.println(F("📶 Card detected!"));

  byte carPlateBuff[16];
  byte balanceBuff[16];
  byte len;

  // Input validation for car plate
  while (true) {
    Serial.println(F("Enter car plate (7 chars, e.g., RAK123A), end with #:"));
    Serial.setTimeout(20000L);
    len = Serial.readBytesUntil('#', (char *)carPlateBuff, 16);

    if (len != 7) {
      Serial.print(F("❌ Invalid length (got "));
      Serial.print(len);
      Serial.println(F("). Must be 7 chars."));
      flushSerial();
      continue;
    }

    // Convert carPlateBuff to String
    char tempPlate[8]; // 7 chars + null terminator
    memcpy(tempPlate, carPlateBuff, 7);
    tempPlate[7] = '\0'; // Null-terminate
    String plate = String(tempPlate);

    if (!isValidPlate(plate)) {
      Serial.println(F("❌ Invalid plate format. Use RA followed by any letter (A-Z), 3 digits, 1 letter (A-Z)."));
      flushSerial();
      continue;
    }

    padBuffer(carPlateBuff, len);
    break;
  }

  // Input validation for balance
  while (true) {
    Serial.println(F("Enter balance (positive number, max 16 chars), end with #:"));
    Serial.setTimeout(20000L);
    len = Serial.readBytesUntil('#', (char *)balanceBuff, 16);

    if (len == 0 || len > 16) {
      Serial.println(F("❌ Invalid balance length."));
      flushSerial();
      continue;
    }

    // Convert balanceBuff to String
    char tempBalance[len + 1]; // len chars + null terminator
    memcpy(tempBalance, balanceBuff, len);
    tempBalance[len] = '\0'; // Null-terminate
    String balanceStr = String(tempBalance);

    if (!isValidBalance(balanceStr)) {
      Serial.println(F("❌ Invalid balance: must be positive number."));
      flushSerial();
      continue;
    }

    padBuffer(balanceBuff, len);
    break;
  }

  byte carPlateBlock = 2;
  byte balanceBlock = 4;

  // Write with error checking
  if (!writeBytesToBlock(carPlateBlock, carPlateBuff)) {
    Serial.println(F("❌ Failed to write car plate."));
  } else if (!writeBytesToBlock(balanceBlock, balanceBuff)) {
    Serial.println(F("❌ Failed to write balance."));
  } else {
    Serial.println(F("✅ Data written successfully:"));
    Serial.print(F("Car Plate: "));
    Serial.println((char*)carPlateBuff);
    Serial.print(F("Balance: "));
    Serial.println((char*)balanceBuff);
  }

  Serial.println(F("🔄 Remove card to write again."));
  mfrc522.PICC_HaltA();
  mfrc522.PCD_StopCrypto1();
  delay(2000);
}

// Validate plate format (e.g., RAK123A)
bool isValidPlate(String plate) {
  if (plate.length() != 7) return false;
  // Check if first two characters are "RA"
  if (!plate.substring(0, 2).equals("RA")) return false;
  // Check if third character is an uppercase letter (A-Z)
  if (!isAlpha(plate.charAt(2)) || !isUpperCase(plate.charAt(2))) return false;
  // Check if next three characters (indices 3-5) are digits
  for (int i = 3; i < 6; i++) {
    if (!isDigit(plate.charAt(i))) return false;
  }
  // Check if last character (index 6) is an uppercase letter
  if (!isAlpha(plate.charAt(6)) || !isUpperCase(plate.charAt(6))) return false;
  return true;
}

// Validate balance format
bool isValidBalance(String balance) {
  if (balance.length() == 0) return false;
  for (int i = 0; i < balance.length(); i++) {
    if (!isDigit(balance.charAt(i))) return false;
  }
  long value = balance.toInt();
  return value >= 0;
}

// Pad buffer with spaces
void padBuffer(byte* buffer, byte len) {
  for (byte i = len; i < 16; i++) {
    buffer[i] = ' ';
  }
}

// Clear serial buffer
void flushSerial() {
  while (Serial.available()) {
    Serial.read();
  }
}

// Write to block with error checking
bool writeBytesToBlock(byte block, byte buff[]) {
  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, block, &key, &(mfrc522.uid));
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Auth failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return false;
  }

  card_status = mfrc522.MIFARE_Write(block, buff, 16);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Write failed: "));
    Serial.println(mfrc522.GetStatusCodeName(card_status));
    return false;
  }
  return true;
}