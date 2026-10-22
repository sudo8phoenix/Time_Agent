FROM node:20-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends default-jre-headless && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml ./
COPY uv.lock ./
RUN python -c "import pathlib,tomllib,subprocess,sys; data=tomllib.loads(pathlib.Path('uv.lock').read_text()); pathlib.Path('/tmp/constraints.txt').write_text(''.join(p['name']+'=='+p['version']+'\n' for p in data['package'] if 'registry' in p.get('source',{}))); deps=tomllib.loads(pathlib.Path('pyproject.toml').read_text())['project']['dependencies']; subprocess.check_call([sys.executable,'-m','pip','install','--no-cache-dir','--constraint','/tmp/constraints.txt',*deps])" \
    && rm /tmp/constraints.txt
COPY backend/app ./backend/app
RUN pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home progress \
    && mkdir -p /app/uploads /run/site-parser \
    && chown -R progress:progress /app/uploads /run/site-parser
COPY ops/ ./ops/
COPY alembic.ini ./
COPY backend/migrations ./backend/migrations
COPY --from=frontend /build/frontend/dist ./frontend/dist
ENV PYTHONPATH=/app/backend PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER progress
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
