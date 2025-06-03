import cv2
from ultralytics import YOLO
import os
import time
import serial
import serial.tools.list_ports
import psycopg2
from collections import Counter
import pytesseract
import re
import random
from datetime import datetime

# Custom exception for critical errors
class CriticalError(Exception):
    pass

# Configuration
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
try:
    if not os.path.isfile(pytesseract.pytesseract.tesseract_cmd):
        raise FileNotFoundError("Tesseract executable not found")
except FileNotFoundError as e:
    print(f"[ERROR] {e}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: {e}\n")
        log_file.flush()
    exit()



model = None
try:
    model = YOLO("best.pt")
except FileNotFoundError as e:
    print(f"[ERROR] YOLO model file not found: {e}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: YOLO model file not found: {e}\n")
        log_file.flush()
    exit()

save_dir = 'plates'
PLATE_PATTERN = r'^[A-Z]{2,3}[0-9]{3}[A-Z]$'
ENTRY_COOLDOWN = 300  # 5 minutes in seconds
DB_CONFIG = {
    'host': 'localhost',
    'user': 'postgres',
    'password': '1234',
    'dbname': 'parking_system'
}

# Database connection
def get_db_connection():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        conn.set_session(autocommit=False)
        return conn
    except psycopg2.Error as e:
        raise CriticalError(f"Database connection failed: {e}")

# Initialize database
def initialize_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS parking_logs (
                id SERIAL PRIMARY KEY,
                plate_number VARCHAR(10) NOT NULL,
                payment_status BOOLEAN NOT NULL DEFAULT FALSE,
                entry_timestamp TIMESTAMP NOT NULL,
                exit_timestamp TIMESTAMP,
                amount NUMERIC(10, 2),
                exited BOOLEAN NOT NULL DEFAULT FALSE,
                CONSTRAINT chk_plate CHECK (plate_number ~ '^[A-Z]{2,3}[0-9]{3}[A-Z]$')
            )
        """)
        cursor.execute("""
            DO $$ BEGIN
                CREATE TYPE event_type AS ENUM ('Entry', 'Exit', 'Payment', 'Unauthorized Exit Attempt', 'Error');
            EXCEPTION
                WHEN duplicate_object THEN NULL;
            END $$;
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS logs (
                id SERIAL PRIMARY KEY,
                plate_number VARCHAR(10) NOT NULL,
                event_type event_type NOT NULL,
                event_timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                message VARCHAR(255) NOT NULL
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        print("[INIT] Database initialized")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Database initialized\n")
            log_file.flush()
    except psycopg2.Error as e:
        raise CriticalError(f"Database initialization failed: {e}")

# Log event to logs table
def log_event(plate, event_type, message, conn):
    try:
        if not conn or conn.closed:
            raise CriticalError("Database connection is closed")
        if len(message) > 255:
            message = message[:252] + "..."
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO logs (plate_number, event_type, event_timestamp, message) VALUES (%s, %s, %s, %s)",
            (plate or "UNKNOWN", event_type, datetime.now(), message)
        )
        conn.commit()
        cursor.close()
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Logged event: {event_type} for {plate or 'UNKNOWN'} - {message}\n")
            log_file.flush()
    except psycopg2.Error as e:
        if conn:
            conn.rollback()
        raise CriticalError(f"Failed to log event for {plate or 'UNKNOWN'}: {e}")

# Validate plate format
def is_valid_plate(plate):
    try:
        if not plate or not isinstance(plate, str):
            return False
        return bool(re.match(PLATE_PATTERN, plate))
    except Exception as e:
        raise CriticalError(f"Plate validation error: {e}")

# Check if plate already has an active entry
def has_active_entry(plate, conn):
    try:
        if not is_valid_plate(plate):
            raise CriticalError(f"Invalid plate format: {plate}")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM parking_logs WHERE plate_number = %s AND payment_status = FALSE",
            (plate,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count > 0
    except psycopg2.Error as e:
        conn.rollback()
        raise CriticalError(f"Failed to check active entry for {plate}: {e}")

# Detect Arduino port
def detect_arduino_port():
    try:
        ports = list(serial.tools.list_ports.comports())
        print(f"[DEBUG] Available ports: {[port.device + ' (' + port.description + ')' for port in ports]}")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Available ports: {[port.device + ' (' + port.description + ')' for port in ports]}\n")
            log_file.flush()
        for port in ports:
            if "Arduino" in port.description or "COM5" in port.description or "USB-SERIAL" in port.description:
                print(f"[INFO] Selected Arduino port: {port.device} ({port.description})")
                return port.device
        raise CriticalError("COM5 not found for gate control")
    except Exception as e:
        raise CriticalError(f"Arduino port detection failed: {e}")

# Mock ultrasonic sensor
def mock_ultrasonic_distance():
    return random.randint(10, 40)

# Trigger buzzer
def trigger_buzzer(ser):
    try:
        if ser and ser.is_open:
            ser.write(b'b')
            ser.flush()
            print("[BUZZER] Buzzer activated")
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Buzzer activated\n")
                log_file.flush()
            time.sleep(2)  # Wait for buzzer to complete
    except serial.SerialException as e:
        print(f"[ERROR] Failed to trigger buzzer: {e}")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Failed to trigger buzzer: {e}\n")
            log_file.flush()

# Initialize
try:
    initialize_db()
except CriticalError as e:
    print(f"[ERROR] {e}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: {e}\n")
        log_file.flush()
    exit()

conn = None
try:
    conn = get_db_connection()
except CriticalError as e:
    print(f"[ERROR] {e}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: {e}\n")
        log_file.flush()
    exit()

arduino = None
try:
    arduino_port = detect_arduino_port()
    if not arduino_port:
        raise CriticalError("Arduino not detected")
    print(f"[CONNECTED] Arduino on {arduino_port}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Connected to Arduino on {arduino_port}\n")
        log_file.flush()
    arduino = serial.Serial(arduino_port, 9600, timeout=1)
    time.sleep(2)
except CriticalError as e:
    print(f"[ERROR] {e}")
    log_event(None, "Error", str(e), conn)
    if arduino and arduino.is_open:
        trigger_buzzer(arduino)
        arduino.close()
    if conn:
        conn.close()
    exit()
except serial.SerialException as e:
    print(f"[ERROR] Failed to connect to Arduino: {e}")
    log_event(None, "Error", f"Failed to connect to Arduino: {e}", conn)
    if conn:
        conn.close()
    exit()

# Main processing
cap = None
try:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise CriticalError("Cannot open webcam")
except CriticalError as e:
    print(f"[ERROR] {e}")
    log_event(None, "Error", str(e), conn)
    trigger_buzzer(arduino)
    if arduino and arduino.is_open:
        arduino.close()
    if conn:
        conn.close()
    exit()

plate_buffer = []
last_saved_plate = None
last_entry_time = 0

print("[SYSTEM] Entry system ready. Press 'q' to exit.")
with open("serial_log.txt", "a") as log_file:
    log_file.write(f"{datetime.now()}: Entry system started\n")
    log_file.flush()

try:
    while True:
        try:
            ret, frame = cap.read()
            if not ret or frame is None or frame.size == 0:
                raise CriticalError("Failed to capture valid frame")

            distance = mock_ultrasonic_distance()
            print(f"[SENSOR] Distance: {distance} cm")

            if distance <= 50:
                results = model(frame)
                for result in results:
                    for box in result.boxes:
                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                        if x2 <= x1 or y2 <= y1 or (x2 - x1) < 50 or (y2 - y1) < 20:
                            print("[WARNING] Invalid ROI, skipping")
                            continue

                        plate_img = frame[y1:y2, x1:x2]
                        if plate_img.size == 0:
                            raise CriticalError("Empty plate image")

                        gray = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
                        blur = cv2.GaussianBlur(gray, (5, 5), 0)
                        thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]

                        plate_text = pytesseract.image_to_string(
                            thresh, config='--psm 8 --oem 3 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
                        ).strip().replace(" ", "")

                        if "RA" in plate_text:
                            start_idx = plate_text.find("RA")
                            plate_candidate = plate_text[start_idx:start_idx + 7]
                            if is_valid_plate(plate_candidate):
                                print(f"[VALID] Plate Detected: {plate_candidate}")
                                with open("serial_log.txt", "a") as log_file:
                                    log_file.write(f"{datetime.now()}: Valid plate detected: {plate_candidate}\n")
                                    log_file.flush()

                                if has_active_entry(plate_candidate, conn):
                                    print(f"[ERROR] Plate {plate_candidate} already has active entry")
                                    log_event(plate_candidate, "Entry", f"Duplicate entry attempt for {plate_candidate}", conn)
                                    trigger_buzzer(arduino)
                                    raise CriticalError(f"Duplicate entry attempt for {plate_candidate}")

                                plate_buffer.append(plate_candidate)
                                timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
                                image_filename = f"{plate_candidate}_{timestamp_str}.jpg"
                                save_path = os.path.join(save_dir, image_filename)

                                try:
                                    os.makedirs(save_dir, exist_ok=True)
                                    if not os.access(save_dir, os.W_OK):
                                        raise CriticalError(f"No write permission for directory: {save_dir}")
                                    cv2.imwrite(save_path, plate_img)
                                    print(f"[IMAGE SAVED] {save_path}")
                                    with open("serial_log.txt", "a") as log_file:
                                        log_file.write(f"{datetime.now()}: Image saved: {save_path}\n")
                                        log_file.flush()
                                except Exception as e:
                                    raise CriticalError(f"Failed to save image: {e}")

                                if len(plate_buffer) >= 3:
                                    most_common = Counter(plate_buffer).most_common(1)[0]
                                    plate, count = most_common[0], most_common[1]

                                    if count < 2:
                                        print("[SKIPPED] Not enough consistent readings")
                                        continue

                                    current_time = time.time()
                                    if (plate != last_saved_plate or
                                            (current_time - last_entry_time) > ENTRY_COOLDOWN):
                                        cursor = conn.cursor()
                                        cursor.execute(
                                            "INSERT INTO parking_logs (plate_number, payment_status, entry_timestamp) VALUES (%s, %s, %s)",
                                            (plate, False, datetime.now())
                                        )
                                        conn.commit()
                                        cursor.close()
                                        log_event(plate, "Entry", f"Vehicle {plate} entered", conn)
                                        print(f"[SAVED] {plate} logged to database")

                                        try:
                                            arduino.write(b'1')
                                            print("[GATE] Opening gate (sent '1')")
                                            with open("serial_log.txt", "a") as log_file:
                                                log_file.write(f"{datetime.now()}: Opening gate (sent '1')\n")
                                                log_file.flush()
                                            time.sleep(15)
                                            arduino.write(b'0')
                                            print("[GATE] Closing gate (sent '0')")
                                            with open("serial_log.txt", "a") as log_file:
                                                log_file.write(f"{datetime.now()}: Closing gate (sent '0')\n")
                                                log_file.flush()
                                        except serial.SerialException as e:
                                            raise CriticalError(f"Arduino communication failed: {e}")

                                        last_saved_plate = plate
                                        last_entry_time = current_time
                                        print("[EXIT] Entry recorded, stopping application")
                                        break
                                    else:
                                        print("[SKIPPED] Duplicate within cooldown period")
                                        log_event(plate, "Entry", f"Duplicate entry attempt within cooldown for {plate}", conn)
                                    plate_buffer.clear()

                        cv2.imshow("Plate", plate_img)
                        cv2.imshow("Processed", thresh)
                        time.sleep(0.5)
            annotated_frame = results[0].plot() if distance <= 50 and 'results' in locals() else frame
            cv2.imshow('Webcam Feed', annotated_frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                print("[EXIT] Program terminated by user")
                log_event(None, "Error", "Program terminated by user", conn)
                break
        except CriticalError as e:
            print(f"[ERROR] {e}")
            log_event(None, "Error", str(e), conn)
            trigger_buzzer(arduino)
            break
        except Exception as e:
            print(f"[ERROR] Unexpected error in main loop: {type(e).__name__}: {str(e)}")
            log_event(None, "Error", f"Unexpected error in main loop: {type(e).__name__}: {str(e)}", conn)
            trigger_buzzer(arduino)
            break
finally:
    if cap:
        cap.release()
    if arduino and arduino.is_open:
        try:
            arduino.close()
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Serial port closed\n")
                log_file.flush()
        except serial.SerialException as e:
            print(f"[ERROR] Failed to close Arduino connection: {e}")
            log_event(None, "Error", f"Failed to close Arduino connection: {e}", conn)
    if conn:
        try:
            conn.close()
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Database connection closed\n")
                log_file.flush()
        except psycopg2.Error as e:
            print(f"[ERROR] Failed to close database connection: {e}")
    cv2.destroyAllWindows()
    print("[CLEANUP] Application terminated")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Application terminated\n")
        log_file.flush()