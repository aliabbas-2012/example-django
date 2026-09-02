FROM python:3.13-slim

# GDAL/GEOS/PROJ are the client-side libraries django.contrib.gis loads via
# ctypes to talk to PostGIS. They only need to exist inside this container,
# not on the host running docker.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin libgdal-dev libgeos-dev libproj-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt requirements-geo.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-geo.txt

COPY . .
