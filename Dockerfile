FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY backend/api/requirements.txt backend/api/requirements.txt
COPY backend/agent/requirements.txt backend/agent/requirements.txt
COPY pipeline/requirements-rag.txt pipeline/requirements-rag.txt
COPY deploy/backend-requirements.txt deploy/backend-requirements.txt
RUN pip install --no-cache-dir -r deploy/backend-requirements.txt \
    && useradd --create-home --uid 10001 appuser
COPY backend/ backend/
COPY data/rates/ data/rates/
COPY data/drafts/executable.json data/drafts/misfiled.json data/drafts/
COPY data/drafts/specs/ data/drafts/specs/
COPY data/processed/chunks.all.jsonl data/processed/chunks.jsonl data/processed/page_map.json data/processed/embeddings.all.gemini-embedding-2.parquet data/processed/
COPY data/raw/standard_estimation/standard-estimation-2026.pdf data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf
RUN python -c "from pathlib import Path; import pymupdf; p=Path('data/raw/standard_estimation/2026_건설공사표준품셈_원문_정오표1차_반영.pdf'); d=pymupdf.open(p); assert len(d)>0; d.close(); required=['chunks.all.jsonl','chunks.jsonl','page_map.json','embeddings.all.gemini-embedding-2.parquet']; assert all((Path('data/processed')/name).is_file() and (Path('data/processed')/name).stat().st_size>0 for name in required), 'Missing serving assets'"
COPY deploy/run_api.py deploy/run_api.py
RUN mkdir -p data/processed/sources && chown appuser:appuser data/processed/sources
USER appuser
EXPOSE 8080
CMD ["python", "deploy/run_api.py"]
