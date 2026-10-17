# the dashboard (AG Studio, React) is built in its own stage, so the final image needs no Node
FROM node:22-alpine AS dashboard
WORKDIR /dashboard
COPY dashboard/package.json dashboard/package-lock.json ./
RUN npm ci
COPY dashboard/ ./
# the AG Studio licence key, when there is one, is read at build time and removes the watermark
ARG VITE_AG_STUDIO_LICENSE
RUN npm run build

FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY --from=dashboard /src/countersign/static/dashboard ./src/countersign/static/dashboard
# editable, so the shop's records are written under /app/data and not inside site-packages
RUN pip install --no-cache-dir -e .
# PayPal's Agent Toolkit, for the owner's assistant. It pins old agent frameworks this project does not use,
# so only the package itself is installed, plus the one library it needs
RUN pip install --no-cache-dir requests && pip install --no-cache-dir --no-deps paypal-agent-toolkit==1.11.0

# with PayPal credentials in the environment the server runs the sandbox shop beside the practice shops,
# without them it runs practice shops only
EXPOSE 8000
CMD ["sh", "-c", "python -m uvicorn --factory countersign.web:create_app --host 0.0.0.0 --port ${PORT:-8000}"]
