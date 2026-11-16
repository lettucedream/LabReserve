#!/bin/sh
(
    set -eu
    psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
        --set availability_password="$AVAILABILITY_DB_PASSWORD" \
        --set booking_password="$BOOKING_DB_PASSWORD" \
        --set waiting_list_password="$WAITING_LIST_DB_PASSWORD" \
        --set notification_password="$NOTIFICATION_DB_PASSWORD" <<'SQL'
CREATE ROLE availability_user LOGIN PASSWORD :'availability_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE booking_user LOGIN PASSWORD :'booking_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE waiting_list_user LOGIN PASSWORD :'waiting_list_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
CREATE ROLE notification_user LOGIN PASSWORD :'notification_password' NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;

CREATE DATABASE availability_db OWNER availability_user;
CREATE DATABASE booking_db OWNER booking_user;
CREATE DATABASE waiting_list_db OWNER waiting_list_user;
CREATE DATABASE notification_db OWNER notification_user;

REVOKE ALL ON DATABASE availability_db FROM PUBLIC;
REVOKE ALL ON DATABASE booking_db FROM PUBLIC;
REVOKE ALL ON DATABASE waiting_list_db FROM PUBLIC;
REVOKE ALL ON DATABASE notification_db FROM PUBLIC;

GRANT CONNECT ON DATABASE availability_db TO availability_user;
GRANT CONNECT ON DATABASE booking_db TO booking_user;
GRANT CONNECT ON DATABASE waiting_list_db TO waiting_list_user;
GRANT CONNECT ON DATABASE notification_db TO notification_user;

ALTER DATABASE availability_db SET timezone TO 'UTC';
ALTER DATABASE booking_db SET timezone TO 'UTC';
ALTER DATABASE waiting_list_db SET timezone TO 'UTC';
ALTER DATABASE notification_db SET timezone TO 'UTC';
SQL
)
