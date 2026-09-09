FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x docker-entrypoint.sh \
    && useradd --create-home --shell /bin/bash companion \
    && chown -R companion:companion /app
USER companion

EXPOSE 8080

# Match contenthub: migrate (pending only) then start API
ENTRYPOINT ["./docker-entrypoint.sh"]
