# OCI Operations Runbook

## Directory Layout

```text
/home/ubuntu/amx/
  production/AMX/
  staging/<slot>/
  gitnexus/
  backups/
  logs/
```

The canonical production checkout is `/home/ubuntu/amx/production/AMX`. During
the Public AMX migration, `/home/ubuntu/amx/production/ConsultantAIP` is retained
only as a compatibility symlink to the canonical checkout. The older
`/home/ubuntu/ConsultantAIP` path is also retained as a compatibility symlink.
Do not deploy new automation against either legacy path.

## Public AMX Path Migration

Run once from the currently deployed checkout before changing the protected
GitHub Environment secret `AMX_PRODUCTION_PATH`:

```bash
bash infra/deploy/migrate-public-amx-runtime.sh
```

The helper is idempotent, updates the checkout origin to Public `BizYan/AMX`,
and refuses to proceed when both canonical and legacy paths are conflicting
real directories.

## Production Deploy

```bash
cd /home/ubuntu/amx/production/AMX
git fetch origin --prune --tags
git checkout --force main
bash infra/deploy/deploy-oci.sh \
  --env production \
  --base-path /home/ubuntu/amx/production/AMX \
  --ref main
bash infra/deploy/health-check.sh --base-url https://amx.yuanda.win
```

## Rollback

```bash
cd /home/ubuntu/amx/production/AMX
bash infra/deploy/rollback-oci.sh \
  --base-path /home/ubuntu/amx/production/AMX \
  --ref <known-good-tag-or-sha>
bash infra/deploy/health-check.sh --base-url https://amx.yuanda.win
```

## Logs

```bash
cd /home/ubuntu/amx/production/AMX
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
