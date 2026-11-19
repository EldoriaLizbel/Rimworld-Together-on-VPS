FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS api
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && install -d -m 0770 -o 10001 -g 10001 /bridge
COPY main.py sync.py rwt_files.py save_summary.py worker.py server_data.py ./
USER 10001:10001
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM ghcr.io/rimworld-together/rimworld-together:26.8.31.1@sha256:fc466d16057c57530e818d1e89e081b0e8a8f33da78244fa99d479dea94e4e5d AS rimworld
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN apt-get update && apt-get install -y --no-install-recommends python3 \
    && rm -rf /var/lib/apt/lists/* \
    && install -d -m 0770 -o 10001 -g 10001 /bridge
COPY supervisor.py rwt_files.py factory_defaults.py world_reset.py /opt/rwt/
RUN --network=none /usr/bin/python3 /opt/rwt/factory_defaults.py
WORKDIR /Data
ENTRYPOINT ["/usr/bin/python3", "/opt/rwt/supervisor.py"]
