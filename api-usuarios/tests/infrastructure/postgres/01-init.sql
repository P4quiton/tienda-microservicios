
\set ON_ERROR_STOP on

\getenv test_password TEST_DB_PASSWORD

CREATE ROLE usr_usuarios_test
    WITH LOGIN
    PASSWORD :'test_password'
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS;

ALTER DATABASE db_usuarios_test
    OWNER TO usr_usuarios_test;

REVOKE ALL PRIVILEGES
    ON DATABASE db_usuarios_test
    FROM PUBLIC;

GRANT CONNECT, TEMPORARY, CREATE
    ON DATABASE db_usuarios_test
    TO usr_usuarios_test;

REVOKE CONNECT
    ON DATABASE postgres
    FROM PUBLIC;

REVOKE CONNECT
    ON DATABASE template1
    FROM PUBLIC;

REVOKE CREATE
    ON SCHEMA public
    FROM PUBLIC;

GRANT USAGE, CREATE
    ON SCHEMA public
    TO usr_usuarios_test;

\unset test_password
