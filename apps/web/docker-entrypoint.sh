#!/bin/sh
set -eu
API_UPSTREAM="${API_UPSTREAM:-http://api:8000}"
# Substitute only API_UPSTREAM; leave nginx $vars intact.
sed "s|\${API_UPSTREAM}|${API_UPSTREAM}|g" /etc/nginx/nginx.conf.template > /tmp/nginx.conf
exec nginx -c /tmp/nginx.conf -g "daemon off;"
