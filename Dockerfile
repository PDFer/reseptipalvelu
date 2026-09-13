FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY reseptipalvelu.py .

EXPOSE 5000

CMD ["python", "reseptipalvelu.py"]
