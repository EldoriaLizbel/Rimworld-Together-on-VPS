FROM python:3.12-slim-bookworm AS api
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && install -d -m 0770 -o 10001 -g 10001 /bridge
COPY main.py sync.py rwt_files.py save_summary.py worker.py ./
USER 10001:10001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM ghcr.io/rimworld-together/rimworld-together:26.8.31.1 AS rimworld
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 0770 -o 10001 -g 10001 /bridge
COPY supervisor.py rwt_files.py factory_defaults.py /opt/rwt/
RUN --network=none /usr/bin/python3 /opt/rwt/factory_defaults.py
WORKDIR /Data
ENTRYPOINT ["/usr/bin/python3", "/opt/rwt/supervisor.py"]
