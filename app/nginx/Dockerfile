FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx.conf /etc/nginx/nginx.conf

# Frontend static files baked into the image at build time.
# GitHub Actions passes --build-context frontend=../frontend
# so this path resolves correctly in CI and locally.
COPY --from=frontend . /var/www/html/

EXPOSE 80
