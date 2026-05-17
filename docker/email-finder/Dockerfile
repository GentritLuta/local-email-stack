FROM golang:1.22-alpine AS build
WORKDIR /src
COPY go.mod go.sum* ./
RUN go mod download || true
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/email-finder ./

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata
COPY --from=build /out/email-finder /usr/local/bin/email-finder
EXPOSE 8080
USER nobody
ENTRYPOINT ["/usr/local/bin/email-finder"]
