# Static page (production-local build) behind nginx. Build context: repository root.
FROM node:24-bookworm-slim AS build
WORKDIR /src
COPY contracts contracts
COPY frontend/package.json frontend/package-lock.json frontend/
RUN cd frontend && npm ci --no-audit --no-fund
COPY frontend frontend
RUN cd frontend && npm run build

FROM nginx:stable-alpine
COPY --from=build /src/frontend/dist /usr/share/nginx/html
# The official image renders templates with the container environment (HTTPS_PORT).
COPY deploy/web/default.conf.template /etc/nginx/templates/default.conf.template
