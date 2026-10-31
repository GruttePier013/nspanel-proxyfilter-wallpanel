# Works on any Alpine- or Debian-based add-on base image (the Supervisor passes BUILD_FROM).
ARG BUILD_FROM=alpine:3.20
FROM ${BUILD_FROM}

RUN if command -v apk >/dev/null 2>&1; then \
        apk add --no-cache python3 py3-aiohttp; \
    else \
        apt-get update && apt-get install -y --no-install-recommends python3 python3-aiohttp \
        && rm -rf /var/lib/apt/lists/*; \
    fi

COPY app /app
EXPOSE 8124 8099
CMD ["python3", "-u", "/app/proxyfilter_wallpanel.py", "--options", "/data/options.json"]
