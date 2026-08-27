# Azure Production Deployment

DueSoon's first production topology is one Ubuntu Linux VM, one attached managed disk, and Docker Compose. Caddy is the only public container. It terminates HTTPS and routes DueSoon API/health paths to FastAPI while all other paths reach the private ntfy service.

## Required inputs

- Azure subscription with permission to create a resource group, VM, managed disk, public IP, DNS label, and NSG rules.
- A globally unique DNS label, producing `<label>.<region>.cloudapp.azure.com`.
- An email address for ACME certificate notices.
- A Canvas base URL and student-scoped read token.
- Generated DueSoon API token, private ntfy topic, ntfy user password, and ntfy access token.
- The ntfy iPhone app, configured for the HTTPS server and private topic.

Never put secrets in command arguments, Git, Compose files, cloud-init, screenshots, or support logs. Store the production environment only at `/etc/duesoon/duesoon.env`, owned by root with mode `0600`.

## Resource shape

Use an Ubuntu 24.04 LTS VM sized `Standard_B2als_v2` (or an equivalent 2-vCPU B-series size) and attach at least a 32 GiB managed disk at LUN 0. Permit inbound TCP 22 only from the operator IP when practical, and public TCP 80/443 plus UDP 443. The cloud-init file installs Docker, formats only the new LUN 0 data disk when it has no filesystem, mounts it at `/mnt/duesoon`, and creates application state directories.

## VM bootstrap

Run these commands from the repository after Azure CLI sign-in, replacing the non-secret names:

```powershell
$resourceGroup = "duesoon-prod-rg"
$location = "northcentralus"
$vmName = "duesoon-prod-vm"
$dnsLabel = "duesoon-unique"

az group create --name $resourceGroup --location $location
az vm create `
  --resource-group $resourceGroup `
  --name $vmName `
  --image Ubuntu2404 `
  --size Standard_B2als_v2 `
  --admin-username azureuser `
  --generate-ssh-keys `
  --public-ip-sku Standard `
  --public-ip-address-dns-name $dnsLabel `
  --data-disk-sizes-gb 64 `
  --custom-data deploy/azure/cloud-init.yml
az vm open-port --resource-group $resourceGroup --name $vmName --port 80 --priority 1010
az vm open-port --resource-group $resourceGroup --name $vmName --port 443 --priority 1020
```

Clone the repository to `/opt/duesoon`. `deploy/azure/provision-runtime.sh` can generate the initial API/ntfy secrets on the VM, create the private ntfy account/ACL/token, and keep the credentials in root-only files without printing them. Canvas remains disabled until its real student token is added. To provision manually, create `/etc/duesoon/duesoon.env` through an SSH session with terminal echo disabled. Required values are:

```dotenv
DUESOON_API_TOKEN=<long-random-value>
DUESOON_DRY_RUN=true
DUESOON_SCHEDULER_ENABLED=false
DUESOON_CANVAS_ENABLED=true
DUESOON_CANVAS_BASE_URL=https://school.instructure.com
DUESOON_CANVAS_ACCESS_TOKEN=<student-read-token>
DUESOON_NTFY_ENABLED=true
DUESOON_NTFY_TOPIC=<private-topic>
DUESOON_NTFY_TOKEN=<ntfy-access-token>
DUESOON_NTFY_TIMEOUT_SECONDS=10
```

## Private ntfy bootstrap

Start ntfy first, then create one regular owner account, grant it read-write access only to the private topic, and issue a token. These commands directly update the managed-disk-backed ntfy auth database:

```bash
cd /opt/duesoon/deploy/azure
docker compose --env-file /etc/duesoon/compose.env -f docker-compose.production.yml up -d ntfy
docker compose --env-file /etc/duesoon/compose.env -f docker-compose.production.yml exec ntfy ntfy user add duesoon-owner
docker compose --env-file /etc/duesoon/compose.env -f docker-compose.production.yml exec ntfy ntfy access duesoon-owner PRIVATE_TOPIC rw
docker compose --env-file /etc/duesoon/compose.env -f docker-compose.production.yml exec ntfy ntfy token add --label="DueSoon publisher" duesoon-owner
```

Put the generated token in `DUESOON_NTFY_TOKEN`, never in Compose or Git. Then start the full stack:

```bash
docker compose --env-file /etc/duesoon/compose.env -f docker-compose.production.yml up -d --build
docker compose --env-file /etc/duesoon/compose.env -f docker-compose.production.yml ps
```

## Activation checks

1. `https://<host>/health/ready` returns database ready.
2. Anonymous access to the private ntfy topic returns 401/403.
3. The iPhone ntfy app is signed into the HTTPS server and subscribed to the private topic.
4. Keep `DUESOON_DRY_RUN=true` for the first API call and verify a `dry_run` audit record.
5. Set `DUESOON_DRY_RUN=false`, recreate only the DueSoon container, and call `POST /api/v1/notifications/test` once with `X-API-Token` and a unique `Idempotency-Key`.
6. The response is `sent`, includes a provider message ID, and repeating the key returns `already_sent` without another phone alert.

Run `sudo bash /opt/duesoon/deploy/azure/verify-runtime.sh` on the VM for a
non-secret check of authenticated API access and anonymous ntfy denial.

Do not enable the scheduler until the checkpoint engine and pre-send Canvas submission recheck are implemented and verified.
