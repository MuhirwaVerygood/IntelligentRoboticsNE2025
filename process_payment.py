import psycopg2
import serial
import time
import serial.tools.list_ports
import platform
from datetime import datetime
import re
import math

RATE_PER_HOUR = 500
PLATE_PATTERN = r'^RA[A-Z][0-9]{3}[A-Z]$'
DB_CONFIG = {
    'host': 'localhost',
    'user': 'postgres',
    'password': '1234',
    'dbname': 'parking_system'
}

# Custom exception for successful payment completion
class PaymentComplete(Exception):
    pass

def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except psycopg2.Error as e:
        print(f"[ERROR] Database connection failed: {e}")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Database connection failed: {e}\n")
            log_file.flush()
        exit()

def log_event(plate, event_type, message, conn):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO logs (plate_number, event_type, event_timestamp, message) VALUES (%s, %s, %s, %s)",
        (plate, event_type, datetime.now(), message)
    )
    conn.commit()
    cursor.close()
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Logged event: {event_type} for {plate} - {message}\n")
        log_file.flush()

def detect_arduino_port():
    ports = list(serial.tools.list_ports.comports())
    print(f"[DEBUG] Available ports: {[port.device + ' (' + port.description + ')' for port in ports]}")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Available ports: {[port.device + ' (' + port.description + ')' for port in ports]}\n")
        log_file.flush()
    for port in ports:
        if port.device == "COM4":  # Explicitly select COM4 for payment
            print(f"[INFO] Selected payment Arduino port: {port.device} ({port.description})")
            return port.device
    print("[ERROR] COM4 not found for payment")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: COM4 not found for payment\n")
        log_file.flush()
    return None

def parse_arduino_data(line):
    print(f"[DEBUG] Raw input: '{line}'")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Raw input: {line}\n")
        log_file.flush()
    if "[TIMEOUT]" in line:
        print(f"[INFO] Arduino timed out, ignoring: {line}")
        return None, None
    try:
        parts = line.strip().split(',')
        print(f"[DEBUG] Parsed parts: {parts}")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Parsed parts: {parts}\n")
            log_file.flush()
        if len(parts) != 2:
            print(f"[ERROR] Invalid data format: {line}")
            return None, None
        plate, balance_str = parts
        plate = plate.strip()
        balance_str = balance_str.strip()
        if not re.match(PLATE_PATTERN, plate):
            print(f"[ERROR] Invalid plate format: {plate}")
            return None, None
        balance = int(balance_str) if balance_str.isdigit() else None
        if balance is None or balance < 0:
            print(f"[ERROR] Invalid balance: {balance_str}")
            return None, None
        return plate, balance
    except ValueError as e:
        print(f"[ERROR] Parsing error: {e}")
        return None, None

def process_payment(plate, balance, ser, conn):
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, entry_timestamp FROM parking_logs WHERE plate_number = %s AND payment_status = FALSE",
            (plate,)
        )
        result = cursor.fetchone()
        if not result:
            print(f"[PAYMENT] Plate {plate} not found or already paid")
            log_event(plate, "Payment", f"Payment attempt for {plate} failed: no unpaid entry", conn)
            cursor.close()
            return

        entry_id, entry_time = result
        exit_time = datetime.now()
        hours_spent = (exit_time - entry_time).total_seconds() / 3600  # Convert to hours
        hours_charged = math.ceil(hours_spent)  # Round up to next hour
        amount_due = hours_charged * RATE_PER_HOUR

        if balance < amount_due:
            print(f"[PAYMENT] Insufficient balance: {balance} < {amount_due}")
            ser.write(b'I\n')
            ser.flush()
            log_event(plate, "Payment", f"Insufficient balance for {plate}: {balance} < {amount_due}", conn)
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Sent: I\n")
                log_file.flush()
            cursor.close()
            return

        new_balance = balance - amount_due
        ser.reset_output_buffer()
        start_time = time.time()
        print("[WAIT] Waiting for Arduino READY...")

        while True:
            if ser.in_waiting:
                arduino_response = ser.readline().decode().strip()
                print(f"[ARDUINO] {arduino_response}")
                with open("serial_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now()}: Received: {arduino_response}\n")
                    log_file.flush()
                if arduino_response == "READY":
                    break
            if time.time() - start_time > 10:
                print("[ERROR] Timeout waiting for Arduino READY")
                log_event(plate, "Payment", f"Payment timeout for {plate}", conn)
                with open("serial_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now()}: Timeout waiting for READY\n")
                    log_file.flush()
                cursor.close()
                return
            time.sleep(0.1)

        ser.write(f"{new_balance}\r\n".encode())
        ser.flush()
        print(f"[PAYMENT] Sent new balance: {new_balance}")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Sent new balance: {new_balance}\n")
            log_file.flush()

        start_time = time.time()
        print("[WAIT] Waiting for Arduino confirmation...")
        while True:
            if ser.in_waiting:
                confirm = ser.readline().decode().strip()
                print(f"[ARDUINO] {confirm}")
                with open("serial_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now()}: Received: {confirm}\n")
                    log_file.flush()
                if "DONE" in confirm:
                    print("[ARDUINO] Write confirmed")
                    cursor.execute(
                        "UPDATE parking_logs SET payment_status = TRUE, exit_timestamp = %s, amount = %s WHERE id = %s",
                        (exit_time, amount_due, entry_id)
                    )
                    conn.commit()
                    log_event(plate, "Payment", f"Payment of {amount_due} successful for {plate}", conn)
                    cursor.close()
                    print(f"[PAYMENT] Successfully processed for {plate}, Amount: {amount_due}")
                    print("[EXIT] Payment completed, stopping application")
                    with open("serial_log.txt", "a") as log_file:
                        log_file.write(f"{datetime.now()}: Payment completed, stopping application\n")
                        log_file.flush()
                    raise PaymentComplete(f"Payment completed for {plate}")
            if time.time() - start_time > 10:
                print("[ERROR] Timeout waiting for confirmation")
                log_event(plate, "Payment", f"Payment confirmation timeout for {plate}", conn)
                with open("serial_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now()}: Timeout waiting for confirmation\n")
                    log_file.flush()
                cursor.close()
                return
            time.sleep(0.1)

    except psycopg2.Error as e:
        print(f"[ERROR] Payment processing failed: {e}")
        log_event(plate, "Payment", f"Payment error for {plate}: {str(e)}", conn)
    except PaymentComplete:
        raise  # Re-raise to be handled in main
    except Exception as e:
        print(f"[ERROR] Unexpected error in payment processing: {e}")
        log_event(plate, "Payment", f"Unexpected payment error for {plate}: {str(e)}", conn)

def connect_serial():
    retry_attempts = 5
    for attempt in range(retry_attempts):
        port = detect_arduino_port()
        if not port:
            print(f"[ERROR] Arduino not found, retrying ({attempt + 1}/{retry_attempts})...")
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Arduino not found, retrying ({attempt + 1}/{retry_attempts})\n")
                log_file.flush()
            time.sleep(1)
            continue
        try:
            ser = serial.Serial(port, 9600, timeout=3)
            time.sleep(6)  # Allow Arduino reset
            ser.reset_input_buffer()
            ser.reset_output_buffer()
            print(f"[CONNECTED] Listening on {port}")
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Connected to {port}\n")
                log_file.flush()
            return ser
        except serial.SerialException as e:
            print(f"[ERROR] Serial connection failed on {port}: {e}")
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Serial connection failed on {port}: {e}\n")
                log_file.flush()
            time.sleep(1)
    print(f"[ERROR] Failed to connect to Arduino after {retry_attempts} attempts")
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Failed to connect to Arduino after {retry_attempts} attempts\n")
        log_file.flush()
    return None

def main():
    conn = get_db_connection()
    ser = None
    payment_completed = False  # Flag to stop serial processing after payment
    with open("serial_log.txt", "a") as log_file:
        log_file.write(f"{datetime.now()}: Program started\n")
        log_file.flush()
    try:
        while True:
            try:
                if payment_completed:
                    break
                if not ser or not ser.is_open:
                    ser = connect_serial()
                    if not ser:
                        time.sleep(5)
                        continue
                if ser.in_waiting:
                    line = ser.readline().decode().strip()
                    with open("serial_log.txt", "a") as log_file:
                        log_file.write(f"{datetime.now()}: Received: {line}\n")
                        log_file.flush()
                    print(f"[SERIAL] Received: {line}")
                    plate, balance = parse_arduino_data(line)
                    if plate and balance is not None:
                        process_payment(plate, balance, ser, conn)
                time.sleep(0.1)
            except serial.SerialException as e:
                print(f"[ERROR] Serial error: {e}")
                with open("serial_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now()}: Serial error: {e}\n")
                    log_file.flush()
                if ser and ser.is_open:
                    ser.close()
                ser = None
                time.sleep(1)
            except PaymentComplete as e:
                print(f"[EXIT] {e}")
                with open("serial_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now()}: {e}\n")
                    log_file.flush()
                payment_completed = True
                break
            except KeyboardInterrupt:
                print(f"[EXIT] Program terminated by user")
                with open("serial_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now()}: Program terminated by user\n")
                    log_file.flush()
                break
            except Exception as e:
                print(f"[ERROR] Unexpected error in main loop: {e}")
                with open("serial_log.txt", "a") as log_file:
                    log_file.write(f"{datetime.now()}: Unexpected error in main loop: {e}\n")
                    log_file.flush()
                time.sleep(1)
    finally:
        if ser and ser.is_open:
            ser.close()
            with open("serial_log.txt", "a") as log_file:
                log_file.write(f"{datetime.now()}: Serial port closed\n")
                log_file.flush()
        conn.close()
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Database connection closed\n")
            log_file.flush()
        print("[CLEANUP] Application terminated")
        with open("serial_log.txt", "a") as log_file:
            log_file.write(f"{datetime.now()}: Application terminated\n")
            log_file.flush()

if __name__ == "__main__":
    main()