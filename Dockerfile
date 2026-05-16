FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libusb-0.1-4 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY controller/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY controller/octofan_controller /app/octofan_controller
COPY reference/octofan-hiveos-originals/fan_controller_cli /opt/octofan/fan_controller_cli
RUN chmod +x /opt/octofan/fan_controller_cli

ENV OCTOFAN_BIN=/opt/octofan/fan_controller_cli
ENV OCTOFAN_CONFIG=/config/octofan.yaml
EXPOSE 8000

CMD ["uvicorn", "octofan_controller.app:app", "--host", "0.0.0.0", "--port", "8000"]
