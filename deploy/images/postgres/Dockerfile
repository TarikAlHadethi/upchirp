# PostgreSQL 16 with TimescaleDB and pgvector: what Upchirp needs, without the 4.4 GB
# high-availability image. pgvector comes from the PGDG repository the base image uses.
FROM postgres:16-bookworm
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
    && curl -fsSL https://packagecloud.io/timescale/timescaledb/gpgkey \
       | gpg --dearmor -o /usr/share/keyrings/timescale.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/timescale.gpg] https://packagecloud.io/timescale/timescaledb/debian/ bookworm main" \
       > /etc/apt/sources.list.d/timescale.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends timescaledb-2-postgresql-16 postgresql-16-pgvector \
    && apt-get purge -y curl gnupg && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && echo "shared_preload_libraries = 'timescaledb'" >> /usr/share/postgresql/postgresql.conf.sample \
    && echo "timescaledb.telemetry_level = off" >> /usr/share/postgresql/postgresql.conf.sample
