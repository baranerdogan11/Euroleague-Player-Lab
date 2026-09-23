FROM python:3.11-slim
WORKDIR /srv
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8000
COPY service/requirements.txt service/requirements.txt
RUN pip install --no-cache-dir -r service/requirements.txt
COPY model/features.py model/xfg_model.joblib model/model_card.json model/registry.json model/shooter_effects_E2025.parquet model/
COPY service/app.py service/app.py
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%s/health' % __import__('os').environ.get('PORT','8000')).status == 200 else 1)"
CMD ["sh", "-c", "uvicorn service.app:app --host 0.0.0.0 --port ${PORT} --workers 2"]
