#include <SPI.h>
#include <MFRC522.h>

#define RST_PIN 9
#define SS_PIN 10

MFRC522 mfrc522(SS_PIN, RST_PIN);
MFRC522::MIFARE_Key key;
MFRC522::StatusCode card_status;

bool awaitingUpdate = false;
bool sentReady = false;
String currentPlate = "";
long currentBalance = 0;
unsigned long readySentTime = 0;
const unsigned long RESPONSE_TIMEOUT = 10000;

void setup() {
  Serial.begin(9600);
  while (!Serial);
  delay(1000); // Added delay for serial stability
  SPI.begin();
  mfrc522.PCD_Init();
  for (byte i = 0; i < 6; i++) {
    key.keyByte[i] = 0xFF;
  }
  Serial.println(F("==== PAYMENT MODE RFID ===="));
  Serial.println(F("Place your card near the reader..."));
}

void loop() {
  if (!awaitingUpdate) {
    if (!mfrc522.PICC_IsNewCardPresent() || !mfrc522.PICC_ReadCardSerial()) return;

    Serial.println(F("📶 Card detected!"));

    currentPlate = readBlockData(2, "Car Plate");
    String balanceStr = readBlockData(4, "Balance");

    // Debug: Print raw data read from card
    Serial.print(F("[DEBUG] Raw Car Plate: "));
    Serial.println(currentPlate);
    Serial.print(F("[DEBUG] Raw Balance: "));
    Serial.println(balanceStr);

    if (currentPlate.startsWith("[") || balanceStr.startsWith("[")) {
      Serial.println(F("⚠️ Invalid card data."));
      mfrc522.PICC_HaltA();
      mfrc522.PCD_StopCrypto1();
      delay(2000);
      return;
    }

    if (!isValidPlate(currentPlate)) {
      Serial.println(F("⚠️ Invalid plate format. Must be RA followed by any letter (A-Z), 3 digits, 1 letter (A-Z)."));
      mfrc522.PICC_HaltA();
      mfrc522.PCD_StopCrypto1();
      delay(2000);
      return;
    }

    if (!isValidBalance(balanceStr)) {
      Serial.println(F("⚠️ Invalid balance format."));
      mfrc522.PICC_HaltA();
      mfrc522.PCD_StopCrypto1();
      delay(2000);
      return;
    }

    currentBalance = balanceStr.toInt();
    // Debug: Confirm data before sending
    Serial.print(F("[DEBUG] Sending to Python: "));
    Serial.print(currentPlate);
    Serial.print(F(","));
    Serial.println(currentBalance);

    Serial.print(currentPlate);
    Serial.print(F(","));
    Serial.println(currentBalance);

    awaitingUpdate = true;
    sentReady = false;
  }

  if (awaitingUpdate && !sentReady) {
    Serial.println(F("READY"));
    sentReady = true;
    readySentTime = millis();
  }

  if (awaitingUpdate && sentReady) {
    if (millis() - readySentTime > RESPONSE_TIMEOUT) {
      Serial.println(F("[TIMEOUT] No response from PC."));
      awaitingUpdate = false;
      sentReady = false;
      mfrc522.PICC_HaltA();
      mfrc522.PCD_StopCrypto1();
      delay(1000);
      return;
    }

    if (Serial.available()) {
      String response = Serial.readStringUntil('\n');
      response.trim();

      Serial.print(F("[RECEIVED]: "));
      Serial.println(response);

      if (response == "I") {
        Serial.println(F("[DENIED] Insufficient balance"));
      } else if (!isValidBalance(response)) {
        Serial.println(F("[ERROR] Invalid balance received."));
      } else {
        long newBalance = response.toInt();
        if (writeBlockData(4, String(newBalance))) {
          Serial.println(F("DONE"));
          Serial.print(F("[UPDATED] New Balance: "));
          Serial.println(newBalance);
        } else {
          Serial.println(F("[ERROR] Failed to write new balance."));
        }
      }

      awaitingUpdate = false;
      sentReady = false;
      mfrc522.PICC_HaltA();
      mfrc522.PCD_StopCrypto1();
      delay(2000);
    }
  }
}

String readBlockData(byte blockNumber, String label) {
  byte buffer[18];
  byte bufferSize = sizeof(buffer);

  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Auth failed for "));
    Serial.println(label);
    return "[Auth Fail]";
  }

  card_status = mfrc522.MIFARE_Read(blockNumber, buffer, &bufferSize);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.print(F("❌ Read failed for "));
    Serial.println(label);
    return "[Read Fail]";
  }

  String data = "";
  for (uint8_t i = 0; i < 16; i++) {
    data += (char)buffer[i];
  }
  data.trim();
  return data;
}

bool writeBlockData(byte blockNumber, String data) {
  byte buffer[16];
  data.trim();
  while (data.length() < 16) data += ' ';
  data.substring(0, 16).getBytes(buffer, 16);

  card_status = mfrc522.PCD_Authenticate(MFRC522::PICC_CMD_MF_AUTH_KEY_A, blockNumber, &key, &(mfrc522.uid));
  if (card_status != MFRC522::STATUS_OK) {
    Serial.println(F("❌ Auth failed on write"));
    return false;
  }

  card_status = mfrc522.MIFARE_Write(blockNumber, buffer, 16);
  if (card_status != MFRC522::STATUS_OK) {
    Serial.println(F("❌ Write failed"));
    return false;
  }
  return true;
}

bool isValidPlate(String plate) {
  if (plate.length() != 7) return false;
  if (!plate.substring(0, 2).equals("RA")) return false;
  if (!isAlpha(plate.charAt(2)) || !isUpperCase(plate.charAt(2))) return false;
  for (int i = 3; i < 6; i++) {
    if (!isDigit(plate.charAt(i))) return false;
  }
  if (!isAlpha(plate.charAt(6)) || !isUpperCase(plate.charAt(6))) return false;
  return true;
}

bool isValidBalance(String balance) {
  if (balance.length() == 0) return false;
  for (int i = 0; i < balance.length(); i++) {
    if (!isDigit(balance.charAt(i))) return false;
  }
  long value = balance.toInt();
  return value >= 0;
}