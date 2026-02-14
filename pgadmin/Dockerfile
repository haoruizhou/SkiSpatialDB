FROM dpage/pgadmin4:latest

COPY servers.json /pgadmin4/servers.json

# Wrap the path in quotes so config_distro.py ends up valid Python:
ENV PGADMIN_CONFIG_DEFAULT_SERVERS_FILE='"/pgadmin4/servers.json"'