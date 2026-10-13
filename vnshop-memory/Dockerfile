# Ứng dụng web VNSHOP Memory (API + giao diện) trong một container.
# Cấu hình bằng biến môi trường của dịch vụ host: NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD,
# NEO4J_DATABASE, GEMINI_API_KEY và VNSHOP_PASSWORD (bắt buộc khi đưa lên Internet).
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY kg ./kg
COPY server ./server
COPY web ./web

RUN useradd --create-home app
USER app

EXPOSE 8000
# --proxy-headers: nhận https/IP thật từ proxy của dịch vụ host (cookie Secure, khoá theo IP).
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
