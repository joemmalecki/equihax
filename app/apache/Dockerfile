FROM php:8.2-apache

# Install PDO MySQL extension
RUN docker-php-ext-install pdo pdo_mysql

# Change Apache to listen on 8080
RUN sed -i 's/Listen 80/Listen 8080/' /etc/apache2/ports.conf
RUN sed -i 's/:80>/:8080>/' /etc/apache2/sites-enabled/000-default.conf

# Backend PHP code baked into the image at build time.
# GitHub Actions passes --build-context backend=../backend
# so this path resolves correctly in CI and locally.
COPY --from=backend . /var/www/html/

RUN chown -R www-data:www-data /var/www/html

EXPOSE 8080
