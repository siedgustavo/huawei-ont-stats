#!/bin/bash
set -e

IMAGE_NAME="ghcr.io/siedgustavo/tools/routerstats"
TAG="${1:-latest}"

echo "Building Docker image: $IMAGE_NAME:$TAG"
docker build -t "$IMAGE_NAME:$TAG" .

# Asume que ya corriste `docker login ghcr.io` con un token que tenga
# permiso write:packages (no se embebe ningún token en este script).
echo "Pushing Docker image to ghcr.io"
docker push "$IMAGE_NAME:$TAG"

echo "Done."
