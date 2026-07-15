FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
ARG VITE_API_BASE=
ARG VITE_ASSET_BASE=/
ARG VITE_TILE_URL=https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png
ENV VITE_API_BASE=$VITE_API_BASE \
    VITE_ASSET_BASE=$VITE_ASSET_BASE \
    VITE_TILE_URL=$VITE_TILE_URL
RUN npm run build

FROM nginx:1.27-alpine AS runtime
COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1/ || exit 1
