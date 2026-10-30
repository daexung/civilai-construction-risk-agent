ARG BASE_IMAGE
FROM ${BASE_IMAGE}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY deploy/calculation_sandbox/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt && mkdir -p pipeline deploy/calculation_sandbox
COPY pipeline/python_sandbox.py pipeline/python_sandbox.py
COPY deploy/calculation_sandbox/app.py deploy/calculation_sandbox/app.py
EXPOSE 8080
CMD ["uvicorn", "deploy.calculation_sandbox.app:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
