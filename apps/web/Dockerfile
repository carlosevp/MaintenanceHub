FROM node:22-alpine AS build
WORKDIR /app
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm install
COPY apps/web/ ./
RUN npm run build

FROM nginx:1.27-alpine
RUN adduser -D -u 10001 appuser \
    && mkdir -p /tmp/client_body /tmp/proxy_temp /tmp/fastcgi_temp /tmp/uwsgi_temp /tmp/scgi_temp \
    && chown -R 10001:0 /usr/share/nginx/html /tmp \
    && chmod -R g+w /tmp
COPY --from=build /app/dist /usr/share/nginx/html
COPY apps/web/nginx.conf.template /etc/nginx/nginx.conf.template
COPY apps/web/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
ENV API_UPSTREAM=http://api:8000
USER 10001
EXPOSE 8080
ENTRYPOINT ["/docker-entrypoint.sh"]
