# OCI Operations Runbook

## Directory Layout

```text
/home/ubuntu/amx/
  production/ConsultantAIP/
  staging/<slot>/
  gitnexus/
  backups/
  logs/
```

## Production Deploy

```bash
cd /home/ubuntu/amx/production/ConsultantAIP
git fetch origin --prune --tags
git checkout --force main
bash infra/deploy/deploy-oci.sh \
  --env production \
  --base-path /home/ubuntu/amx/production/ConsultantAIP \
  --ref main
bash infra/deploy/health-check.sh --base-url https://amx.yuanda.win
```

## Rollback

```bash
cd /home/ubuntu/amx/production/ConsultantAIP
bash infra/deploy/rollback-oci.sh \
  --base-path /home/ubuntu/amx/production/ConsultantAIP \
  --ref <known-good-tag-or-sha>
bash infra/deploy/health-check.sh --base-url https://amx.yuanda.win
```

## Logs

```bash
cd /home/ubuntu/amx/production/ConsultantAIP
docker compose -f infra/docker-compose.yml ps
docker compose -f infra/docker-compose.yml logs --tail=200 api
docker compose -f infra/docker-compose.yml logs --tail=200 worker
docker compose -f infra/docker-compose.yml logs --tail=200 web
```

## Nginx

Install `infra/nginx/amx.conf` as:

```bash
sudo cp infra/nginx/amx.conf /etc/nginx/sites-available/amx.conf
sudo ln -sf /etc/nginx/sites-available/amx.conf /etc/nginx/sites-enabled/amx.conf
sudo nginx -t
sudo systemctl reload nginx
```

The config expects:

```text
/etc/nginx/certs/amx.yuanda.win.pem
/etc/nginx/certs/amx.yuanda.win.key
```
