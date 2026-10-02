#!/bin/bash
# PostgreSQL security hardening
# Execute au premier demarrage du conteneur via /docker-entrypoint-initdb.d/
# POSTGRES_USER et POSTGRES_DB sont injectes par docker-compose depuis .env
set -e

DB_READONLY_PASSWORD=$(cat /run/secrets/db_readonly_password)

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    -- Restreindre l'acces a la base au seul utilisateur applicatif
    REVOKE CONNECT ON DATABASE "$POSTGRES_DB" FROM PUBLIC;
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO "$POSTGRES_USER";

    -- Revoquer la creation dans le schema public (defaut depuis PostgreSQL 15, explicite ici)
    REVOKE CREATE ON SCHEMA public FROM PUBLIC;

    -- Utilisateur lecture seule pour Adminer (SELECT uniquement, aucune ecriture possible)
    -- Connexion Adminer : user="${DB_READONLY_USER}", mot de passe dans secrets/db_readonly_password.txt
    CREATE USER "${DB_READONLY_USER}" WITH PASSWORD '${DB_READONLY_PASSWORD}';
    GRANT CONNECT ON DATABASE "$POSTGRES_DB" TO "${DB_READONLY_USER}";
    GRANT USAGE ON SCHEMA public TO "${DB_READONLY_USER}";
    -- SELECT sur les tables existantes et sur toutes les tables futures crees par l'utilisateur applicatif
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO "${DB_READONLY_USER}";
    ALTER DEFAULT PRIVILEGES FOR ROLE "${POSTGRES_USER}" IN SCHEMA public
        GRANT SELECT ON TABLES TO "${DB_READONLY_USER}";
EOSQL
