# Oracle Cloud setup — create the instance, then deploy

Do steps 1–6 once in the OCI web console (~10 minutes), then run the deploy
script from your machine.

## 0. Prerequisites

- An Oracle Cloud account (Always Free tier is enough)
- This repo with a filled-in `.env` (NVIDIA_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)

## 1. Generate an SSH key (local machine, once)

```bash
ssh-keygen -t ed25519 -f ~/.ssh/oci_key -N ""
```

You'll paste the **public** key (`~/.ssh/oci_key.pub` content) into the console
in step 4.

## 2. Create the compartment (optional but tidy)

Console → Identity & Security → Compartments → **Create Compartment**
Name: `jobspy`. Everything below can live in it.

## 3. Create the instance

Console (choose your home region, e.g. "Home region") → Compute → Instances →
**Create instance**.

- **Name:** `jobspy-lite`
- **Image:** Ubuntu 22.04 (canonical image, not Oracle Linux)
- **Shape:** click "Edit"
  - **Best:** Ampere A1 — `VM.Standard.A1.Flex`, 2 OCPU / 12 GB RAM
    (Always Free gives you 4 OCPU / 24 GB across instances; if "out of capacity"
    errors appear, try a different Availability Domain or retry later — this is
    a known OCI free-tier quirk)
  - **Fallback:** `VM.Standard.E2.1.Micro` (x86, 1 GB RAM) — the cloud-init
    script adds swap so the build fits, but A1 is much more comfortable
- **Networking:** leave the defaults (new VCN + public subnet). Note the
  **public subnet** — the instance needs a public IP.
- **SSH keys:** "Paste a public key" → paste the contents of `~/.ssh/oci_key.pub`
- **Show advanced options** → **Management** tab → **Add cloud-init script** →
  "Paste cloud-init script" → paste the full contents of `deploy/cloud-init.yaml`
- **Create**

Wait for the instance state to become **RUNNING** (~1 min), then copy its
**Public IP address** from the instance details page.

## 4. Open port 8000 in the Security List (console)

The VCN's default Security List only allows SSH. The cloud-init script opens
the OS firewall, but OCI's *cloud* firewall also needs the port:

Console → Networking → Virtual Cloud Networks → your VCN → **Security Lists** →
"Default Security List for ..." → **Add Ingress Rules**:

- **Rule 1:** Source CIDR `0.0.0.0/0`, IP Protocol `TCP`, Destination Port Range `8000`
- **Rule 2 (optional, for a future reverse proxy):** same but port `80`

## 5. First SSH contact

```bash
ssh -i ~/.ssh/oci_key ubuntu@<PUBLIC_IP> "cloud-init status --wait; docker --version"
```

First boot takes 2–3 minutes (packages + swap). Expect something like
`Docker version 27.x`.

## 6. Deploy the app

From this repo's root on your local machine:

```bash
bash deploy/deploy-oci.sh ubuntu@<PUBLIC_IP>
```

This packs the repo **including `.env`**, streams it to `~/app` on the server,
builds the image there (correct architecture automatically), starts the stack,
and health-checks it.

When it finishes:

```bash
# from your machine — check the health endpoint through the public IP
curl http://<PUBLIC_IP>:8000/health
```

Then open **http://<PUBLIC_IP>:8000** in a browser and:

1. Upload your resume (.docx)
2. Set threshold / experience window if needed
3. **Start scheduler**

> Data persists on the server in `~/app/data` (bind-mounted volume).

## 7. Keeping it running / updating

```bash
# logs
ssh ubuntu@<IP> "cd ~/app && docker compose logs -f --tail 50"

# redeploy after code changes (same command as step 6)
bash deploy/deploy-oci.sh ubuntu@<PUBLIC_IP>

# restart / stop
ssh ubuntu@<IP> "cd ~/app && docker compose restart"
ssh ubuntu@<IP> "cd ~/app && docker compose down"
```

`docker-compose.yml` already sets `restart: unless-stopped`, so the stack comes
back after reboots on its own — including the cron scheduler (its enabled flag
is stored in SQLite).

## Hardening notes (do these if this faces the internet)

- The API has no authentication. Anyone who finds the IP can read your jobs,
  upload a resume, or start runs. For anything beyond private testing, put a
  reverse proxy with basic auth or an OAuth proxy (e.g. Caddy + `forward_auth`,
  or Cloudflare Access) in front, or restrict port 8000 in the Security List to
  your own IP (`<your-ip>/32`).
- Consider moving `docker compose` behind Caddy on port 80/443 with a domain.
