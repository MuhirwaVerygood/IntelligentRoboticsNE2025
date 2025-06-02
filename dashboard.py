from flask import Flask, render_template, jsonify
import psycopg2
from datetime import datetime

app = Flask(__name__)

DB_CONFIG = {
    'host': 'localhost',
    'user': 'postgres',
    'password': '1234',
    'dbname': 'parking_system'
}

def get_db_connection():
    try:
        return psycopg2.connect(**DB_CONFIG)
    except psycopg2.Error as e:
        print(f"[ERROR] Database connection failed: {e}")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/logs')
def get_logs():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500

    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM logs ORDER BY event_timestamp DESC LIMIT 100")
        logs = cursor.fetchall()
        formatted_logs = [
            {
                'id': log[0],
                'plate_number': log[1],
                'event_type': log[2],
                'event_timestamp': log[3].strftime('%Y-%m-%d %H:%M:%S'),
                'message': log[4]
            } for log in logs
        ]
        cursor.close()
        conn.close()
        return jsonify(formatted_logs)
    except psycopg2.Error as e:
        print(f"[ERROR] Failed to fetch logs: {e}")
        conn.close()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)