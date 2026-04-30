FROM python:3.9-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV API_IP=
ENV API_USER=
ENV API_PASS=
ENV PYTHONUNBUFFERED=1
CMD ["python", "api_server.py"]