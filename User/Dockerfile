FROM python:3.10-slim

WORKDIR /app

COPY User/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY User/ .

ENV PYTHONUNBUFFERED=1
ENV PORT=8000

CMD ["python", "main.py"]