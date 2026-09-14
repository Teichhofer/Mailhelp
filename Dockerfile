FROM python:3.12.10-slim
WORKDIR /app
COPY pyproject.toml README.md requirements.lock ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.lock && pip install --no-cache-dir --no-deps .
USER 65532:65532
ENTRYPOINT ["mailhelp"]
CMD ["--check", "--config-directory", "/config"]
