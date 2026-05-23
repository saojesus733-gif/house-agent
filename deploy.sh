#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f .env ]; then
  echo "未找到 .env。请先执行：cp .env.example .env，然后填写 DB_PASSWORD、DEEPSEEK_API_KEY、POSTGRES_PASSWORD。"
  exit 1
fi

if grep -q "change_me_before_deploy\\|replace_me" .env; then
  echo ".env 里还有占位符，请先填写真实的 DB_PASSWORD、DEEPSEEK_API_KEY、POSTGRES_PASSWORD。"
  exit 1
fi

echo "====== 构建并启动 House Agent ======"
docker compose up -d --build

echo "====== 服务状态 ======"
docker compose ps

echo "====== 健康检查 ======"
sleep 8
curl -fsS http://127.0.0.1:8001/docs >/dev/null && echo "后端 OK: http://服务器IP:8001/docs"
curl -fsS http://127.0.0.1:5500/static/house.html >/dev/null && echo "前端 OK: http://服务器IP:5500/static/house.html"

echo "====== 完成 ======"
