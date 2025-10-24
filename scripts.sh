#!/bin/bash
set -e

case "$1" in
  up)
    docker-compose up --build
    ;;
  down)
    docker-compose down
    ;;
  logs)
    docker-compose logs -f
    ;;
  backend)
    docker-compose exec backend bash
    ;;
  frontend)
    docker-compose exec frontend sh
    ;;
  *)
    echo "Usage: ./scripts.sh [up|down|logs|backend|frontend]"
    ;;
esac
