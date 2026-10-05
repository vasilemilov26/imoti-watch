FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 TZ=Europe/Sofia
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt tzdata
COPY . .
EXPOSE 8090
CMD ["python", "server.py"]
