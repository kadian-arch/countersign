FROM python:3.14-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
# editable, so the shop's records are written under /app/data and not inside site-packages
RUN pip install --no-cache-dir -e .

# with PayPal credentials in the environment the server runs the sandbox shop beside the practice shops,
# without them it runs practice shops only
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn --factory countersign.web:create_app --host 0.0.0.0 --port ${PORT:-8000}"]
