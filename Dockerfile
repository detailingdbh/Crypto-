FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot/ bot/
COPY run.py backtest.py ./

RUN useradd --create-home trader && mkdir -p /app/data && chown trader /app/data
USER trader

CMD ["python", "run.py", "--config", "config.yaml"]
