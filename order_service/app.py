import os
import datetime
import json
import uuid
import msgpack
from flask import Flask, request, jsonify
import mysql.connector
from kafka import KafkaProducer
import time # Untuk sleep jika ada isu koneksi awal

app = Flask(__name__)

# Konfigurasi MySQL dari Environment Variables
MYSQL_HOST = os.getenv('MYSQL_HOST', 'localhost')
MYSQL_USER = os.getenv('MYSQL_USER', 'root')
MYSQL_PASSWORD = os.getenv('MYSQL_PASSWORD', 'gusdanencintajuli') # PASTIKAN SAMA DENGAN DOCKER-COMPOSE
MYSQL_DB = os.getenv('MYSQL_DB', 'distributed_system_db')

# Konfigurasi Kafka dari Environment Variables
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'localhost:9092')
KAFKA_TOPIC = "order_data_topic" # Nama topik Kafka yang akan digunakan (Konsisten dengan docker-compose)

producer = None

def get_mysql_connection(retries=5, delay=5):
    """Mencoba koneksi MySQL dengan retry."""
    for i in range(retries):
        try:
            conn = mysql.connector.connect(
                host=MYSQL_HOST,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                database=MYSQL_DB
            )
            print(f"Berhasil terhubung ke MySQL: {MYSQL_HOST}")
            return conn
        except mysql.connector.Error as err:
            print(f"Percobaan {i+1}/{retries}: Gagal terhubung ke MySQL: {err}")
            if i < retries - 1:
                time.sleep(delay)
    raise Exception("Tidak dapat terhubung ke MySQL setelah beberapa percobaan.")

def init_mysql_table():
    """Menginisialisasi tabel 'orders' jika belum ada."""
    conn = None
    cursor = None
    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                id INT AUTO_INCREMENT PRIMARY KEY,
                price INT,
                qty INT,
                total INT,
                user_id VARCHAR(255),
                created_at DATETIME
            )
        """)
        conn.commit()
        print("Tabel 'orders' MySQL berhasil diperiksa/dibuat.")
    except Exception as e:
        print(f"Error saat menginisialisasi tabel MySQL: {e}")
        # Dalam kasus gagal inisialisasi, aplikasi mungkin tidak bisa berjalan normal
        # Pertimbangkan untuk keluar atau mencoba kembali
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

def get_kafka_producer(retries=5, delay=5):
    """Mencoba koneksi KafkaProducer dengan retry."""
    global producer
    if producer is not None and producer.bootstrap_connected():
        return producer

    for i in range(retries):
        try:
            print(f"Percobaan {i+1}/{retries}: Mencoba menyambungkan Kafka Producer ke {KAFKA_BOOTSTRAP_SERVERS}...")
            # value_serializer adalah fungsi yang akan mengemas data menjadi bytes sebelum dikirim ke Kafka
            prod = KafkaProducer(bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                                 value_serializer=lambda v: msgpack.packb(v, use_bin_type=True),
                                 api_version=(0, 10, 1)) # Bisa membantu dengan kompatibilitas Redpanda
            # Coba kirim pesan dummy kecil untuk verifikasi koneksi
            # Ini akan memblokir sampai ada metadata atau error
            prod.send(KAFKA_TOPIC, {"_test_connection": True}).get(timeout=5)
            print("Kafka Producer berhasil terhubung.")
            producer = prod
            return producer
        except Exception as e:
            print(f"Error menyambungkan Kafka Producer: {e}")
            if i < retries - 1:
                time.sleep(delay)
    raise Exception("Tidak dapat menyambungkan Kafka Producer setelah beberapa percobaan.")

@app.before_request
def ensure_connections():
    """Pastikan koneksi database dan Kafka siap sebelum setiap permintaan."""
    try:
        global producer
        if producer is None or not producer.bootstrap_connected():
            get_kafka_producer()
    except Exception as e:
        print(f"Error in before_request: {e}")


@app.route('/request_data', methods=['POST'])
def request_data():
    conn = None
    cursor = None
    try:
        # 1. Menerima Data (JSON atau Msgpack)
        if request.headers.get('Content-Type') == 'application/x-msgpack':
            data = msgpack.unpackb(request.get_data(), raw=False)
            print(f"[*] Menerima data Msgpack dari klien: {data}")
        elif request.is_json:
            data = request.get_json()
            print(f"[*] Menerima data JSON dari klien: {data}")
        else:
            return jsonify({"error": "Content-Type tidak didukung. Gunakan application/json atau application/x-msgpack"}), 415

        if not data:
            return jsonify({"error": "Data input tidak valid atau kosong."}), 400

        # 2. Validasi Data
        required_fields = ["price", "qty", "total", "user_id"]
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"Field '{field}' yang diperlukan hilang."}), 400
        
        price = data['price']
        qty = data['qty']
        total = data['total']
        user_id = data['user_id']

        # Validasi format UUID V4
        try:
            uuid.UUID(user_id, version=4)
        except ValueError:
            return jsonify({"error": "user_id tidak valid. Harus format UUID V4."}), 400

        mysql_insert_success = False
        
        # 3. Insert ke MySQL
        try:
            conn = get_mysql_connection()
            cursor = conn.cursor()
            sql = "INSERT INTO orders (price, qty, total, user_id, created_at) VALUES (%s, %s, %s, %s, %s)"
            values = (price, qty, total, user_id, datetime.datetime.now())
            cursor.execute(sql, values)
            conn.commit()
            mysql_insert_success = True
            print("[*] Data berhasil disisipkan ke MySQL.")
        except mysql.connector.Error as err:
            print(f"[!] Error saat menyisipkan ke MySQL: {err}")
            mysql_insert_success = False
        finally:
            if cursor: cursor.close()
            if conn and conn.is_connected(): conn.close()

        # 4. Publikasikan Pesan ke Kafka (dalam format Msgpack)
        try:
            kafka_producer = get_kafka_producer() # Dapatkan producer yang sudah terinisialisasi
            message_to_kafka = {
                "topic": KAFKA_TOPIC,
                "message": data, # Data permintaan asli
                "sender": "my-flask-api",
                "created_at": datetime.datetime.now().isoformat(),
                "status": mysql_insert_success
            }
            # Pesan akan otomatis dikemas Msgpack oleh value_serializer
            future = kafka_producer.send(KAFKA_TOPIC, message_to_kafka)
            record_metadata = future.get(timeout=10) # Tunggu hingga pesan terkirim atau timeout
            print(f"[*] Pesan berhasil dipublikasikan ke Kafka: Topic={record_metadata.topic}, Partition={record_metadata.partition}, Offset={record_metadata.offset}")

            return jsonify({
                "status": "success",
                "mysql_insert_status": mysql_insert_success,
                "kafka_publish_status": True,
                "message": "Data diproses, disimpan ke MySQL, dan dikirim ke Kafka."
            }), 200

        except Exception as kafka_e:
            print(f"[!] Error saat mempublikasikan ke Kafka: {kafka_e}")
            return jsonify({
                "status": "error",
                "mysql_insert_status": mysql_insert_success,
                "kafka_publish_status": False,
                "message": f"Data disimpan ke MySQL tetapi gagal dikirim ke Kafka: {str(kafka_e)}"
            }), 500

    except Exception as e:
        print(f"[!] Terjadi error di endpoint /request_data: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    # Pastikan MySQL siap dan tabel terinisialisasi sebelum menjalankan Flask
    print("Mencoba inisialisasi tabel MySQL...")
    init_mysql_table()
    
    # Pastikan Kafka Producer siap
    print("Mencoba inisialisasi Kafka Producer...")
    get_kafka_producer()

    print("Menjalankan Flask Order Service...")
    app.run(host='0.0.0.0', port=5000)
