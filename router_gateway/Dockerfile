# router_gateway 独立镜像：gateway-api 与 gateway-worker 同镜像、不同 command。
# 供应商 token / OSS 凭证一律运行时由环境变量注入，绝不进镜像。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    PIP_DEFAULT_TIMEOUT=120

WORKDIR /app

# 依赖单独成层以利用构建缓存；全部为 wheel 安装，无需编译工具链
COPY requirements.txt .
RUN pip install --no-cache-dir --retries 5 -r requirements.txt

# ffmpeg：成片转存前流复制剥离 mp4 容器元数据（防厂商侧信道），仅用二进制无需编解码库外资源
# Debian 源切阿里云镜像（与 PIP_INDEX_URL 同源策略，上海 ECS 构建可达性）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g; s|security.debian.org|mirrors.aliyun.com|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true; \
    apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# 非 root 运行
RUN groupadd -r gateway && useradd -r -g gateway -u 1001 gateway

# 仅复制网关包（含 catalog/routes.yaml 台账）
COPY --chown=gateway:gateway . ./router_gateway

USER gateway

EXPOSE 8088

# 默认 api；compose 中 gateway-worker 覆盖为 python -m router_gateway.worker
CMD ["python", "-m", "router_gateway.api"]
