import datetime

import psycopg2
import re

# Configuration
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
        return psycopg2.connect(**DB_CONFIG)
    except psycopg2.Error as e:
        print(f"[ERROR] Database connection failed: {e}")
        exit()

# Log event to logs table
def log_event(plate, event_type, message, conn):
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO logs (plate_number, event_type, event_timestamp, message) VALUES (%s, %s, %s, %s)",
        (plate, event_type, datetime.now(), message)
    )
    conn.commit()
    cursor.close()

# Mark payment as successful
def mark_payment_success(plate_number):
    if not re.match(PLATE_PATTERN, plate_number):
        print(f"[ERROR] Invalid plate format: {plate_number}")
        return

    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM parking_logs WHERE plate_number = %s AND payment_status = FALSE",
            (plate_number,)
        )
        result = cursor.fetchone()
        if not result:
            print(f"[INFO] No unpaid record found for {plate_number}")
            log_event(plate_number, "Payment", f"No unpaid record for {plate_number}", conn)
            cursor.close()
            conn.close()
            return

        cursor.execute(
            "UPDATE parking_logs SET payment_status = TRUE WHERE id = %s",
            (result[0],)
        )
        conn.commit()
        log_event(plate_number, "Payment", f"Manually marked as paid for {plate_number}", conn)
        print(f"[UPDATED] Payment status set to TRUE for {plate_number}")
    except psycopg2.Error as e:
        print(f"[ERROR] Failed to update payment status: {e}")
        log_event(plate_number, "Payment", f"Payment update error for {plate_number}: {str(e)}", conn)
    finally:
        cursor.close()
        conn.close()

# Testing usage
if __name__ == "__main__":
    plate = input("Enter plate number to mark as paid: ").strip().upper()
    mark_payment_success(plate)