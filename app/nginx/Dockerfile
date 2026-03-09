FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf

COPY nginx/nginx.conf /etc/nginx/nginx.conf

# Frontend static files — build context is the app/ directory.
COPY frontend/ /var/www/html/

EXPOSE 80
