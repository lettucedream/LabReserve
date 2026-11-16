FROM nginx:1.30.6-alpine3.24@sha256:0e52bd054126cdc040b1276c0af347aeb02a41b9cfe305d6094767ac30e97949
COPY infra/frontend/nginx.conf /etc/nginx/nginx.conf
COPY frontend/ /usr/share/nginx/html/
USER 101
EXPOSE 8080
