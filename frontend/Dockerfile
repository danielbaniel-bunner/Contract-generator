FROM node:20-alpine AS build
WORKDIR /app

# Install deps (cache-friendly)
COPY package.json ./
# COPY package-lock.json ./   # if you have one
RUN npm i

# Copy everything (including .env)
COPY . .

# Build static assets (Vite will read VITE_BACKEND_URL from .env)
RUN npm run build

# ---- Runtime stage ----
FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
