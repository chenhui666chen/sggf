# 构建阶段
FROM node:18-alpine as builder

WORKDIR /app

ARG VITE_API_URL=/api
ARG VITE_WS_URL=/socket.io
ARG VITE_APP_NAME="Novel Writing System"
ARG VITE_APP_VERSION=1.0.0

ENV VITE_API_URL=$VITE_API_URL
ENV VITE_WS_URL=$VITE_WS_URL
ENV VITE_APP_NAME=$VITE_APP_NAME
ENV VITE_APP_VERSION=$VITE_APP_VERSION

COPY package*.json ./

RUN npm ci

COPY . .

RUN node node_modules/vite/bin/vite.js build

# 生产阶段
FROM node:18-alpine

WORKDIR /app

RUN npm install -g serve

COPY --from=builder /app/dist ./dist

EXPOSE 3000

CMD ["serve", "-s", "dist", "-l", "3000"]
