FROM node:24.18.1-bookworm-slim
WORKDIR /app
ENV NODE_ENV=production
COPY package.json package-lock.json ./
RUN npm ci --omit=dev
COPY src ./src
COPY migrations ./migrations
COPY docker/entrypoint.sh /usr/local/bin/api-carrito-entrypoint
RUN chmod 0755 /usr/local/bin/api-carrito-entrypoint
USER node
EXPOSE 8005
ENTRYPOINT ["api-carrito-entrypoint"]
CMD ["node", "src/server.js"]
