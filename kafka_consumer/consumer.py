import os
import json
import time
import msgpack
from kafka import KafkaConsumer
import requests # Import pustaka requests
from datetime import datetime

# --- DEBUGGING AWAL ---
print(">>> consumer.py: Skrip dimulai.")

# Konfigurasi Kafka dari Environment Variables
KAFKA_BOOTSTRAP_SERVERS = os.getenv('KAFKA_BOOTSTRAP_SERVERS', 'redpanda:29092')
# PENTING: Gunakan KAFKA_TOPIC dari environment variable, yang diatur di docker-compose.yml
# Defaultnya harus sesuai dengan yang di docker-compose.yml jika tidak ada env var
KAFKA_TOPIC = os.getenv('KAFKA_TOPIC', 'redpanda_status') # <-- DIPERBAIKI DI SINI
KAFKA_CONSUMER_GROUP_ID = os.getenv('KAFKA_CONSUMER_GROUP_ID', 'supabase-data-pipeline-group')

# Konfigurasi Supabase dari Environment Variables
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_KEY')

print(f">>> consumer.py: KAFKA_BOOTSTRAP_SERVERS: {KAFKA_BOOTSTRAP_SERVERS}")
print(f">>> consumer.py: KAFKA_TOPIC: {KAFKA_TOPIC}")
print(f">>> consumer.py: SUPABASE_URL (sebagian): {SUPABASE_URL[:8]}...") # Hindari menampilkan full key

if not SUPABASE_URL or not SUPABASE_KEY:
    print("Variabel lingkungan SUPABASE_URL atau SUPABASE_KEY tidak diatur. Keluar.")
    exit(1) # Keluar dari skrip jika kredensial tidak ada

# URL untuk PostgREST API Supabase
SUPABASE_REST_URL = f"{SUPABASE_URL}/rest/v1/data_contract" # Langsung ke tabel data_contract
print(f">>> consumer.py: SUPABASE_REST_URL: {SUPABASE_REST_URL}")


def get_kafka_consumer(retries=10, delay=10):
    """Mencoba mendapatkan Kafka Consumer dengan retry."""
    for i in range(retries):
        try:
            print(f"Percobaan {i+1}/{retries}: Mencoba menyambungkan Kafka Consumer ke {KAFKA_BOOTSTRAP_SERVERS}...")
            consumer = KafkaConsumer(
                KAFKA_TOPIC,
                bootstrap_servers=KAFKA_BOOTSTRAP_SERVERS,
                auto_offset_reset='earliest', # Mulai dari awal jika tidak ada offset tersimpan
                enable_auto_commit=True, # Otomatis commit offset
                group_id=KAFKA_CONSUMER_GROUP_ID,
                value_deserializer=lambda m: msgpack.unpackb(m, raw=False), # Deserialisasi Msgpack
                # api_version=(0, 10, 1) # <-- DIHAPUS: Biarkan KafkaConsumer menegosiasikan API version secara otomatis
            )
            print(f"Konsumen Kafka berhasil terhubung ke topik: {KAFKA_TOPIC}")
            return consumer
        except Exception as e:
            print(f"Error menyambungkan Kafka Consumer: {e}")
            if i < retries - 1:
                time.sleep(delay)
    raise Exception("Tidak dapat menyambungkan Kafka Consumer setelah beberapa percobaan.")

def insert_into_supabase(data):
    """Menyisipkan data yang diterima dari Kafka ke Supabase menggunakan requests."""
    try:
        # Data 'message' dari Kafka adalah dictionary asli dari API, simpan sebagai string JSON
        message_content = json.dumps(data.get("message"))
        
        # Pastikan created_at adalah format ISO 8601 yang diterima Supabase
        created_at_str = data.get("created_at")
        
        supabase_payload = {
            "topic": data.get("topic", KAFKA_TOPIC),
            "message": message_content,
            "sender": data.get("sender", "unknown-sender"),
            "created_at": created_at_str,
            "status": data.get("status", False)
        }
        
        headers = {
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
            "Content-Type": "application/json",
            "Prefer": "return=representation" # Meminta Supabase mengembalikan data yang disisipkan
        }
        
        # Melakukan POST request langsung ke API PostgREST Supabase
        response = requests.post(SUPABASE_REST_URL, headers=headers, json=supabase_payload)
        response.raise_for_status() # Akan memunculkan HTTPError untuk status kode 4xx/5xx

        response_data = response.json()
        if response_data:
            print(f"[*] Data berhasil disisipkan ke Supabase: {response_data}")
            return True
        else:
            print(f"[!] Penyisipan Supabase gagal atau tidak mengembalikan data. Respons: {response.text}")
            return False
    except requests.exceptions.RequestException as req_e:
        print(f"[!] Error saat menyisipkan ke Supabase (HTTP Request): {req_e}")
        if hasattr(req_e, 'response') and req_e.response is not None:
            print(f"[!] Supabase Response Error: {req_e.response.text}")
        return False
    except Exception as e:
        print(f"[!] Error saat menyisipkan ke Supabase: {e}")
        return False

if __name__ == '__main__':
    print(">>> consumer.py: Memulai eksekusi main block.")
    # Verifikasi kredensial Supabase di awal
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("Kredensial Supabase tidak lengkap. Konsumen tidak dapat memulai.")
        exit(1)

    consumer = None
    try:
        consumer = get_kafka_consumer()
    except Exception as e:
        print(f"Gagal memulai konsumen Kafka: {e}")
        exit(1)

    print(f"Konsumen Kafka mulai mendengarkan di topik: {KAFKA_TOPIC}")

    while True:
        try:
            for message in consumer:
                print(f"\n[*] Menerima pesan baru:")
                print(f"  Topic: {message.topic}")
                print(f"  Partition: {message.partition}")
                print(f"  Offset: {message.offset}")
                
                received_data = message.value # Sudah dideserialisasi Msgpack oleh value_deserializer
                print("  Konten pesan yang didekode:", received_data)

                insert_into_supabase(received_data)

        except Exception as e:
            print(f"[!] Error dalam loop konsumen Kafka: {e}")
            print("Mencoba menyambungkan kembali konsumen Kafka...")
            if consumer:
                consumer.close() # Tutup konsumen lama
            time.sleep(5)
            try:
                consumer = get_kafka_consumer()
            except Exception as reconnect_e:
                print(f"[!] Gagal menyambungkan kembali konsumen: {reconnect_e}. Mencoba lagi dalam 10 detik.")
                time.sleep(10)
