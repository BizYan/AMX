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

Production deploys require explicit Owner Go and must use the repository
`Deploy production` GitHub Actions workflow. The manual OCI commands below are
for break-glass diagnosis or documented rollback operations only; they must not
be used to bypass candidate verification, exact SHA evidence, health,
authenticated smoke, provenance, teardown, or rollback verification.

Before the first deployment with runtime security guardrails:

```bash
cd /home/ubuntu/amx/production/AMX
chmod 600 .env
```

The production `.env` must keep `POSTGRES_BIND_ADDRESS`,
`REDIS_BIND_ADDRESS`, `API_BIND_ADDRESS`, and `WEB_BIND_ADDRESS` unset or set
to `127.0.0.1`. The deployment preflight rejects public bind addresses.

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

After any approved deployment, verify the workflow evidence instead of relying
only on manual shell output:

- deployed ref and deployed SHA match the approved tag or SHA;
- production `/health` passed;
- authenticated production smoke passed;
- GitNexus refresh passed;
- deployment provenance passed;
- rollback target still resolves and remains usable.

## Rollback

```bash
cd /home/ubuntu/amx/production/AMX
bash infra/deploy/rollback-oci.sh \
  --base-path /home/ubuntu/amx/production/AMX \
  --ref <known-good-tag-or-sha>
bash infra/deploy/health-check.sh --base-url https://amx.yuanda.win
```

Rollback also requires health, authenticated smoke, provenance, service status,
and GitNexus verification when applicable.

If rollback, redeploy, or rollback verification repeats the same gate failure,
stop additional rollback loops. Preserve the workflow URL, OCI command output,
service status, container logs, health/smoke/provenance output, deployed ref/SHA,
and rollback target evidence. Compare the candidate verification gates with the
production gates, classify the failure, and open the smallest forward
compatibility or workflow fix. Retry production deployment only after the fix
passes CI and the owner grants Owner Go. This does not change break-glass
rollback behavior for unrelated catastrophic failures that leave production
unsafe or unavailable.

Before the first real client and after recovery-sensitive changes, run the
non-production recovery drill in `docs/runbooks/recovery-drill.md`. That drill
proves backup restore and application rollback without destructive database
downgrade. It must not restore production data without explicit Owner Go.

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
