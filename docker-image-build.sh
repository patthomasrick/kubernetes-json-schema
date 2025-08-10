#!/usr/bin/env bash

set -e
set -o pipefail

# CD to current directory
cd "$(dirname "$0")" || exit $?

docker --context=desktop-linux buildx build \
  --platform linux/amd64,linux/arm64 \
  -t patthomasrick/openapi2jsonschema:latest \
  docker-openapi2jsonschema \
  --push
