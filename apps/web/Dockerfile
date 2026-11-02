FROM node:22-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build
FROM node:22-alpine
WORKDIR /app
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static

# Docker sets HOSTNAME=<container-id>; the Next.js standalone server binds to
# that name, which resolves to a single interface when the container is on
# multiple networks. Force 0.0.0.0 so the server listens on every interface.
ENV HOSTNAME=0.0.0.0

EXPOSE 3000
CMD ["node", "server.js"]
