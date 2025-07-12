# Gunakan Python 3.9 slim-buster sebagai base image
FROM python:3.9-slim-buster

# Tetapkan direktori kerja di dalam kontainer
WORKDIR /app

# Salin file requirements.txt ke direktori kerja
COPY requirements.txt .

# Instal dependensi Python
RUN pip install --no-cache-dir -r requirements.txt

# Salin seluruh kode aplikasi ke direktori kerja
COPY . .

# Perintah untuk menjalankan aplikasi saat kontainer dimulai
CMD ["python", "app.py"]
