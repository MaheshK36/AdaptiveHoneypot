FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY fake_db_server.py ./fake_db_server.py

CMD ["python", "fake_db_server.py"]