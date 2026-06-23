# ── Build Stage ──────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

# Layer cache: install dependencies before copying source
COPY package.json package-lock.json* ./
RUN npm install

# CRA bakes REACT_APP_* vars into the JS bundle at build time (not runtime).
# The ARG must be declared before ENV so docker build --build-arg works.
ARG REACT_APP_API_BASE
ENV REACT_APP_API_BASE=$REACT_APP_API_BASE

COPY . .
RUN npm run build

# ── Runtime Stage ─────────────────────────────────────────────
FROM nginx:alpine

COPY --from=build /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
