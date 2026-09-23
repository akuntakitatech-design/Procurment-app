# =============================================================
# ProcureFlow / Procurement — Frontend (React CRA) di Nginx
# Base directory di Coolify: /frontend  |  Build pack: Dockerfile  |  Port: 80
# Env runtime: BACKEND_URL (contoh: http://backend-procurement:8000)
# =============================================================
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json yarn.lock* ./
RUN yarn install --frozen-lockfile || yarn install
COPY . .
# Kosong = frontend memanggil path relatif /api (diproksi Nginx ke backend)
ARG REACT_APP_BACKEND_URL=""
ENV REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL} \
    GENERATE_SOURCEMAP=false \
    CI=true
RUN yarn build

FROM nginx:1.27-alpine AS runtime
ENV BACKEND_URL=http://backend:8000 \
    NGINX_PORT=80 \
    CLIENT_MAX_BODY_SIZE=50m
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY nginx/05-normalize-backend-url.envsh /docker-entrypoint.d/05-normalize-backend-url.envsh
COPY nginx/16-resolver-fallback.envsh /docker-entrypoint.d/16-resolver-fallback.envsh
RUN chmod +x /docker-entrypoint.d/05-normalize-backend-url.envsh /docker-entrypoint.d/16-resolver-fallback.envsh
COPY --from=build /app/build /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=5 \
  CMD wget -qO- http://127.0.0.1:${NGINX_PORT}/healthz || exit 1
CMD ["nginx", "-g", "daemon off;"]
