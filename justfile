set dotenv-load

run:
    python app.py

req:
    pip-compile requirements.in

init-docker-buildx:
  docker buildx use builder || docker buildx create --name builder --use

docker tag="gaoyifan/chatgpt-slack-bot": init-docker-buildx
  docker buildx build --platform linux/amd64,linux/arm64 \
    --tag={{tag}} \
    --push .
