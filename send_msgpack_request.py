import requests
import msgpack
import uuid
import json # Untuk mencetak respons dengan indah

# Data contoh berdasarkan kontrak Anda
data_to_send = {
    "price": 25,
    "qty": 3,
    "total": 75,
    "user_id": str(uuid.uuid4()) # Menghasilkan UUID v4 baru secara otomatis
}

# Kemas data menggunakan msgpack
packed_data = msgpack.packb(data_to_send, use_bin_type=True)

# Konfigurasi permintaan
url = "http://localhost:8080/request_data" # Gunakan port 8080 sesuai konfigurasi Anda
headers = {'Content-Type': 'application/x-msgpack'}

print(f"Mengirim data (Msgpack) ke {url}:")
print(f"  Data: {data_to_send}")

try:
    # Kirim permintaan POST dengan data Msgpack dan header yang sesuai
    response = requests.post(url, data=packed_data, headers=headers)

    # Cek apakah ada error HTTP (4xx atau 5xx)
    response.raise_for_status() 

    print("\nRespons dari Order Service:")
    print(f"  Status Code: {response.status_code}")
    # Asumsi Flask API mengembalikan JSON
    print(f"  Body: {json.dumps(response.json(), indent=2)}") 

except requests.exceptions.RequestException as e:
    print(f"\n[!] Error saat mengirim permintaan: {e}")
    if hasattr(e, 'response') and e.response is not None:
        print(f"  Respons Error: {e.response.text}")
except Exception as e:
    print(f"\n[!] Terjadi error yang tidak terduga: {e}")