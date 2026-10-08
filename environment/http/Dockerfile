FROM python:3.11-slim

WORKDIR /srv/fake-http

COPY requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /srv/fake-http/sessions

ENTRYPOINT ["uvicorn"]