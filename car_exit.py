import cv2
from ultralytics import YOLO
import pytesseract
import os
import time
import serial
import serial.tools.list_ports
import psycopg2
from collections import Counter
import random
import re
from datetime import datetime
from colorama import init, Fore, Style

# Initialize colorama
init()

# Custom exception
class CriticalError(Exception):
    pass

# Configuration
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
try:
    if not os.path.isfile(pytesseract.pytesseract.tesseract_cmd):
        raise FileNotFoundError("Tesseract executable not found")
except FileNotFoundError as e:
    print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: {e}\n")
        log_file.flush()
    exit()

model = None
try:
    model = YOLO(r'best.pt')
except FileNotFoundError as e:
    print(f"{Fore.RED}[ERROR] YOLO model file not found: {e}{Style.RESET_ALL}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: YOLO model file not found: {e}\n")
        log_file.flush()
    exit()

PLATE_PATTERN = r'^[A-Z]{2,3}[0-9]{3}[A-Z]$'
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
        print(f"{Fore.GREEN}[INIT] Database initialized{Style.RESET_ALL}")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Database initialized\n")
            log_file.flush()
    except psycopg2.Error as e:
        print(f"{Fore.RED}[ERROR] Database initialization failed: {e}{Style.RESET_ALL}")
        raise CriticalError(f"Database initialization failed: {e}")

# Log event
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

# Check unpaid record
def has_unpaid_record(plate, conn):
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
        raise CriticalError(f"Failed to check unpaid record for {plate}: {e}")

# Check payment status
def is_payment_complete(plate, conn):
    try:
        if not is_valid_plate(plate):
            raise CriticalError(f"Invalid plate format: {plate}")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT payment_status FROM parking_logs WHERE plate_number = %s AND payment_status = TRUE AND exited = FALSE",
            (plate,)
        )
        result = cursor.fetchone()
        cursor.close()
        return result is not None
    except psycopg2.Error as e:
        conn.rollback()
        raise CriticalError(f"Failed to check payment status for {plate}: {e}")

# Check valid record
def has_valid_record(plate, conn):
    try:
        if not is_valid_plate(plate):
            raise CriticalError(f"Invalid plate format: {plate}")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM parking_logs WHERE plate_number = %s AND (payment_status = FALSE OR payment_status = TRUE)",
            (plate,)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count > 0
    except psycopg2.Error as e:
        conn.rollback()
        raise CriticalError(f"Failed to check record for {plate}: {e}")

# Update exit timestamp
def update_exit_timestamp(plate, conn):
    try:
        if not is_valid_plate(plate):
            raise CriticalError(f"Invalid plate format: {plate}")
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, exit_timestamp, exited FROM parking_logs WHERE plate_number = %s AND payment_status = TRUE AND exited = FALSE",
            (plate,)
        )
        result = cursor.fetchone()
        if not result:
            print(f"{Fore.RED}[INFO] No valid paid and non-exited record for {plate}{Style.RESET_ALL}")
            log_event(plate, "Exit", f"No paid and non-exited record for {plate}", conn)
            cursor.close()
            return False

        entry_id, exit_timestamp, exited = result
        if exited:
            print(f"{Fore.RED}[INFO] Exit already recorded for {plate} (ID: {entry_id}){Style.RESET_ALL}")
            log_event(plate, "Exit", f"Exit already recorded for {plate} (ID: {entry_id})", conn)
            cursor.close()
            return False

        cursor.execute(
            "UPDATE parking_logs SET exit_timestamp = %s, exited = TRUE WHERE id = %s",
            (datetime.now(), entry_id)
        )
        conn.commit()
        log_event(plate, "Exit", f"Vehicle {plate} exited (ID: {entry_id})", conn)
        cursor.close()
        print(f"{Fore.GREEN}[INFO] Updated exit timestamp for {plate} (ID: {entry_id}){Style.RESET_ALL}")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Updated exit timestamp for {plate} (ID: {entry_id})\n")
            log_file.flush()
        return True
    except psycopg2.Error as e:
        conn.rollback()
        raise CriticalError(f"Failed to update exit timestamp for {plate}: {e}")

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
                print(f"{Fore.GREEN}[INFO] Selected Arduino port: {port.device} ({port.description}){Style.RESET_ALL}")
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
            ser.write(b'2')
            ser.flush()
            print(f"{Fore.RED}[BUZZER] Buzzer activated{Style.RESET_ALL}")
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Buzzer activated\n")
                log_file.flush()
            time.sleep(1.5)  # Match Arduino's 3x(250ms on + 250ms off)
            print(f"{Fore.RED}[BUZZER] Buzzer deactivated{Style.RESET_ALL}")
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Buzzer deactivated\n")
                log_file.flush()
    except serial.SerialException as e:
        print(f"{Fore.RED}[ERROR] Failed to trigger buzzer: {e}{Style.RESET_ALL}")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Failed to trigger buzzer: {e}\n")
            log_file.flush()

# Initialize
try:
    initialize_db()
except CriticalError as e:
    print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: {e}\n")
        log_file.flush()
    exit()

conn = None
try:
    conn = get_db_connection()
    print(f"{Fore.GREEN}[INFO] Database connected{Style.RESET_ALL}")
except CriticalError as e:
    print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: {e}\n")
        log_file.flush()
    exit()

arduino = None
try:
    arduino_port = detect_arduino_port()
    if not arduino_port:
        raise CriticalError("Arduino not detected")
    print(f"{Fore.GREEN}[CONNECTED] Arduino on {arduino_port}{Style.RESET_ALL}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Connected to Arduino on {arduino_port}\n")
        log_file.flush()
    arduino = serial.Serial(arduino_port, 9600, timeout=3)
    time.sleep(5)
except CriticalError as e:
    print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
    log_event(None, "Error", str(e), conn)
    if conn:
        conn.close()
    exit()
except serial.SerialException as e:
    print(f"{Fore.RED}[ERROR] Failed to connect to Arduino: {e}{Style.RESET_ALL}")
    log_event(None, "Error", f"Failed to connect to Arduino: {e}", conn)
    if conn:
        conn.close()
    exit()

cap = None
try:
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        raise CriticalError("Cannot open webcam")
except CriticalError as e:
    print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
    log_event(None, "Error", str(e), conn)
    trigger_buzzer(arduino)
    if arduino and arduino.is_open:
        arduino.close()
    if conn:
        conn.close()
    exit()

plate_buffer = []
print(f"{Fore.GREEN}[INFO] Exit system started{Style.RESET_ALL}")
with open("serial_log.txt", "a") as log_file:
    log_file.write(f"{datetime.now()}: Exit system started\n")
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
                            print(f"{Fore.RED}[WARNING] Invalid ROI, skipping{Style.RESET_ALL}")
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
                                print(f"{Fore.GREEN}[VALID] Plate Detected: {plate_candidate}{Style.RESET_ALL}")
                                with open("serial_log.txt", "a") as log_file:
                                    log_file.write(f"{datetime.now()}: Valid plate detected: {plate_candidate}\n")
                                    log_file.flush()

                                if not has_valid_record(plate_candidate, conn):
                                    print(f"{Fore.RED}[DENIED] No active entry or paid record for {plate_candidate}{Style.RESET_ALL}")
                                    log_event(plate_candidate, "Unauthorized Exit Attempt", f"No record for {plate_candidate}", conn)
                                    trigger_buzzer(arduino)
                                    continue

                                plate_buffer.append(plate_candidate)

                                if len(plate_buffer) >= 3:
                                    most_common = Counter(plate_buffer).most_common(1)[0]
                                    plate, count = most_common[0], most_common[1]

                                    if count < 2:
                                        print(f"{Fore.RED}[SKIPPED] Not enough consistent readings{Style.RESET_ALL}")
                                        continue

                                    plate_buffer.clear()

                                    if has_unpaid_record(plate, conn):
                                        print(f"{Fore.RED}[DENIED] Unpaid record found for {plate}{Style.RESET_ALL}")
                                        log_event(plate, "Unauthorized Exit Attempt", f"Unpaid record for {plate}", conn)
                                        trigger_buzzer(arduino)
                                        continue

                                    if is_payment_complete(plate, conn):
                                        print(f"{Fore.GREEN}[GRANTED] Payment complete for {plate}{Style.RESET_ALL}")
                                        try:
                                            arduino.write(b'1')
                                            print(f"{Fore.GREEN}[GATE] Opening gate (sent '1'){Style.RESET_ALL}")
                                            with open("serial_log.txt", "a") as log_file:
                                                log_file.write(f"{datetime.now()}: Opening gate (sent '1')\n")
                                                log_file.flush()
                                            time.sleep(15)
                                            arduino.write(b'0')
                                            print(f"{Fore.GREEN}[GATE] Closing gate (sent '0'){Style.RESET_ALL}")
                                            with open("serial_log.txt", "a") as log_file:
                                                log_file.write(f"{datetime.now()}: Closing gate (sent '0')\n")
                                                log_file.flush()
                                            if update_exit_timestamp(plate, conn):
                                                print(f"{Fore.GREEN}[EXIT] Exit recorded for {plate}{Style.RESET_ALL}")
                                                log_event(plate, "Exit", "Gate closed and exit recorded", conn)
                                        except serial.SerialException as e:
                                            raise CriticalError(f"Arduino communication failed: {e}")
                                    else:
                                        print(f"{Fore.RED}[DENIED] No paid and non-exited record for {plate}{Style.RESET_ALL}")
                                        log_event(plate, "Unauthorized Exit Attempt", f"No paid and non-exited record for {plate}", conn)
                                        trigger_buzzer(arduino)
                                        continue

                        cv2.imshow("Plate", plate_img)
                        cv2.imshow("Processed", thresh)
                        time.sleep(0.5)
            annotated_frame = results[0].plot() if distance <= 50 and 'results' in locals() else frame
            cv2.imshow("Exit Webcam Feed", annotated_frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                print(f"{Fore.RED}[EXIT] Program terminated by user{Style.RESET_ALL}")
                log_event(None, "Error", "Program terminated by user", conn)
                break
        except CriticalError as e:
            print(f"{Fore.RED}[ERROR] {e}{Style.RESET_ALL}")
            log_event(None, "Error", str(e), conn)
            trigger_buzzer(arduino)
            continue
        except Exception as e:
            print(f"{Fore.RED}[ERROR] Unexpected error: {type(e).__name__}: {str(e)}{Style.RESET_ALL}")
            log_event(None, "Error", f"Unexpected error: {type(e).__name__}: {str(e)}", conn)
            trigger_buzzer(arduino)
            continue
finally:
    if cap:
        cap.release()
    if arduino and arduino.is_open:
        try:
            arduino.close()
            print(f"{Fore.GREEN}[CLEANUP] Serial port closed{Style.RESET_ALL}")
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Serial port closed\n")
                log_file.flush()
        except serial.SerialException as e:
            print(f"{Fore.RED}[ERROR] Failed to close Arduino connection: {e}{Style.RESET_ALL}")
            log_event(None, "Error", f"Failed to close Arduino connection: {e}", conn)
    if conn:
        try:
            conn.close()
            print(f"{Fore.GREEN}[CLEANUP] Database connection closed{Style.RESET_ALL}")
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Database connection closed\n")
                log_file.flush()
        except psycopg2.Error as e:
            print(f"{Fore.RED}[ERROR] Failed to close database connection: {e}{Style.RESET_ALL}")
    cv2.destroyAllWindows()
    print(f"{Fore.GREEN}[CLEANUP] Application terminated{Style.RESET_ALL}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Application terminated\n")
        log_file.flush()