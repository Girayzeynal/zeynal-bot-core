FROM cloudflare/cloudflared:latest

COPY config.yml /etc/cloudflared/config.yml

CMD ["tunnel", "--config", "/etc/cloudflared/config.yml", "run"]
