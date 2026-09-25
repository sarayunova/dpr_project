FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini .
COPY alembic/ alembic/
COPY app/ app/
COPY static/ static/

EXPOSE 8000

# Apply any pending migrations on every start, so an upgraded image
# brings its schema with it after an unattended restart -- no manual
# `alembic upgrade head` step to forget.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
