# 8.0: the central Inboxstride sign-in service as its own image (Planung 8.0, section 7).
# Build from the repository root: docker build -f ops/auth/Dockerfile -t inboxstride-auth:<version> .
# Only the service package and its pinned subset of requirements.lock; no Mailhelp code.
FROM python:3.12.16-slim
WORKDIR /app
COPY ops/auth/requirements.lock ./requirements.lock
RUN pip install --no-cache-dir --no-deps -r requirements.lock
COPY src/inboxstride_auth ./inboxstride_auth
ENV PYTHONPATH=/app PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# State, key file, log and TLS material come in as bind mounts; see ops/server/auth.compose.example.yaml.
RUN mkdir -p /state /secrets /logs && chown 65532:65532 /state /logs
USER 65532:65532
# Public callback (behind nginx) and the internal mTLS interface.
EXPOSE 8780 8443
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8780/health', timeout=4)"]
ENTRYPOINT ["python", "-m", "inboxstride_auth"]
CMD ["serve"]
