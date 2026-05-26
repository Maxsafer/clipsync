#!/bin/sh
# Bind mounts arrive owned by whoever created the host directory (often root
# under rootful docker). Fix ownership as root, then drop privileges.
set -e
mkdir -p /data
chown -R clipsync:clipsync /data
exec gosu clipsync "$@"
