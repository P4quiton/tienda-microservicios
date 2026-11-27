FROM golang:1.26.11-alpine AS build

WORKDIR /src
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/api-inventario ./cmd/api

FROM alpine:3.22 AS runtime

RUN apk add --no-cache ca-certificates tzdata \
    && addgroup -S -g 10001 app \
    && adduser -S -D -H -u 10001 -G app app

ENV APP_ENV=production

COPY --from=build --chown=app:app /out/api-inventario /usr/local/bin/api-inventario

USER app
EXPOSE 8004

HEALTHCHECK --interval=30s --timeout=3s --start-period=15s --retries=3 \
    CMD wget -q -O /dev/null http://127.0.0.1:8004/health || exit 1

ENTRYPOINT ["/usr/local/bin/api-inventario"]
