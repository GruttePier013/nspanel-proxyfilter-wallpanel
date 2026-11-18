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
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s --retries=3 \
    CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8124/__health', timeout=4).status == 200 else 1)"
CMD ["python3", "-u", "/app/proxyfilter_wallpanel.py", "--options", "/data/options.json"]
