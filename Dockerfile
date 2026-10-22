# Offline by default: no API key needed. Built and run here with podman 5.4 on Debian 13; the same file works with docker.
#   docker build -t galatiq-invoices .
#   docker run --rm galatiq-invoices                                   # the 20 samples, offline
#   docker run --rm galatiq-invoices pytest -q                         # the offline test suite
#   docker run --rm -v galatiq-state:/app/state galatiq-invoices ...   # keep the database (review queue, history) between runs
#   docker run --rm -e XAI_API_KEY galatiq-invoices python main.py --batch data/invoices --mode live
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 COLUMNS=160 INVENTORY_DB=/app/state/inventory.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir --disable-pip-version-check -r requirements.txt
COPY . .
RUN useradd --create-home app && mkdir -p /app/state && chown -R app /app
USER app

CMD ["python", "main.py", "--batch", "data/invoices", "--offline"]
