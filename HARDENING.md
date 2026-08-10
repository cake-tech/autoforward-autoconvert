# Hardening guide

How to install autoforward-autoconvert on a fresh server without giving away the wallets. Written for Ubuntu 24.04 LTS; adapt the package commands for other distributions.

## What an attacker gets

This box holds a wallet seed in plaintext in `.env` for every asset you enable — up to four (`BITCOIN_WALLET_SEED`, `LITECOIN_WALLET_SEED`, `LITECOIN_MWEB_WALLET_SEED`, `MONERO_WALLET_SEED`) — plus a Kraken API key. Two things follow, and they drive every decision below.

**The balance at risk is small.** autoforward sweeps every 4.5-5.5 minutes, so the hot wallets normally hold only a few minutes of incoming donations, plus dust under the send minimums, plus anything held back when `MAX_NETWORK_FEE_PERCENT` says fees are too high to be worth forwarding.

**The seeds are not small.** A seed is a permanent credential. Deposit addresses are derived from it and handed out to donors, so whoever reads `.env` can drain every future donation to those addresses, quietly, arriving before autoforward does. You would notice only by reconciling donations against Kraken deposits. Assume seed disclosure is unrecoverable without rotating seeds *and* reissuing every published address.

So: protect the seeds like they are the whole treasury, and configure Kraken so that losing the box does not also lose whatever has already been swept.

## If you only do four things

1. **Issue the Kraken API key without withdrawal permission, and restrict it to this server's IP.** This is the single highest-leverage control: it caps a total box compromise at the hot-wallet float instead of the entire Kraken balance.
2. **Give this box one job.** No other services, no other users. `.env` mode `0600`, owned by a non-root deploy user.
3. **SSH: keys only, no root login, no password authentication.**
4. **Default-deny inbound firewall, and never publish the wallet RPC ports.** Nothing in this stack needs an inbound connection except SSH.

Everything else is worth doing. These four are worth doing first.

---

## 1. Provision the box

Any provider is fine. 2 GB RAM is comfortable; the Monero wallet RPC is the heaviest process.

Use a dedicated instance. Not the box running your website, not the box a contractor has access to. Every additional service is another way to reach `.env`, and every additional user is another account that can read it.

If the provider offers it, take the option to supply your SSH public key at creation time so the instance never has a password-authenticated root account.

## 2. Create a deploy user

Do not run the stack as root.

```bash
sudo adduser --disabled-password --gecos "" deploy
sudo usermod -aG sudo deploy
sudo install -d -m 700 -o deploy -g deploy /home/deploy/.ssh
sudo cp ~/.ssh/authorized_keys /home/deploy/.ssh/authorized_keys
sudo chown deploy:deploy /home/deploy/.ssh/authorized_keys
sudo chmod 600 /home/deploy/.ssh/authorized_keys
```

**Verify:** open a *new* terminal and confirm `ssh deploy@<server-ip>` works before you move on. Keep your current session open until it does.

## 3. Harden SSH

Write a drop-in so a package upgrade cannot silently revert it:

```bash
sudo tee /etc/ssh/sshd_config.d/99-hardening.conf >/dev/null <<'EOF'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
AuthenticationMethods publickey
EOF
sudo sshd -t && sudo systemctl reload ssh
```

`KbdInteractiveAuthentication no` matters. On Ubuntu, `PasswordAuthentication no` alone can still leave a password path open through PAM keyboard-interactive.

**Verify**, from your workstation — this must fail:

```bash
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no deploy@<server-ip>
```

Expect `Permission denied (publickey)`. Again, keep a working session open while you test.

## 4. Firewall

Nothing here accepts inbound connections except SSH.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw enable
```

**One caveat worth understanding:** Docker writes its own iptables rules and a *published* container port bypasses UFW entirely. This stack publishes no ports, so UFW is sufficient as shipped — but if you ever add a `ports:` entry to `docker-compose.yml`, that port becomes reachable from the internet regardless of what `ufw status` says. Restrict such rules in the `DOCKER-USER` chain, not in UFW.

**Verify** from another machine — both should time out or be refused:

```bash
nc -zv <server-ip> 7000
nc -zv <server-ip> 18082
```

## 5. Automatic security updates

```bash
sudo apt update && sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

To also apply kernel updates, allow automatic reboots at a quiet hour:

```bash
sudo tee /etc/apt/apt.conf.d/51-autoreboot >/dev/null <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
EOF
```

This is safe here: the long-running containers use `restart: unless-stopped` and come back on their own. After the first reboot, confirm with `docker compose ps` that they did.

## 6. Consider disabling swap

Seeds live in process environment and memory. Swap can write them to disk, where they persist after the process exits.

```bash
free -h                    # check you have headroom first
sudo swapoff -a
sudo sed -i '/\sswap\s/s/^/#/' /etc/fstab
```

Skip this if the box has under 2 GB of RAM — an OOM kill that stops autoforward is worse than the swap risk, because balances then accumulate in the hot wallets. If you keep swap, use an encrypted swap device.

## 7. Install Docker

Use Docker's official repository, not the distribution package, so you get security updates promptly.

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker deploy
```

Note that membership in the `docker` group is equivalent to root on this box. Only the deploy user should have it.

Log out and back in for the group to take effect.

## 8. Set up the Kraken API key

Do this before deploying, in the Kraken web interface. Create a key with **only** these permissions:

| Permission | Why | Endpoint |
| - | - | - |
| Query funds | Read balances before trading | `/0/private/Balance` |
| Deposit funds | Generate sweep destination addresses | `/0/private/DepositAddresses` |
| Create & modify orders | Place the conversion orders | `/0/private/AddOrder` |

**Leave withdrawal permission off.** The programs never call a withdrawal endpoint, so disabling it breaks nothing — and it is what stops a compromised box from draining the exchange balance. If Kraken's interface names these differently, match on the endpoints above.

Then restrict the key to this server's IP address under the key's IP allowlist setting. A key that only works from one address is far less useful to someone who has copied it off the box.

Use a Kraken account dedicated to this program, as the README recommends, so it cannot interfere with other activity.

**Moving funds off Kraken** is a separate process that must use separate credentials — ideally a manual, human-approved withdrawal to storage you control. Once funds are swept, Kraken is the custodian; decide deliberately how long you leave them there.

## 9. Clone the repository and write `.env`

The deploy workflow expects the checkout in the deploy user's home directory:

```bash
cd ~
git clone https://github.com/MAGICGrants/autoforward-autoconvert.git
cd autoforward-autoconvert
```

Create `.env` with restrictive permissions *before* writing secrets into it, so it is never briefly world-readable:

```bash
install -m 600 .env.example .env
```

`install` copies and sets the mode in one step. A plain `cp` would create the file using your umask, which on most systems means world-readable for the moment before you fix it.

**Set `COMPOSE_PROFILES` to only the assets you actually accept.** Every asset you leave out is one fewer seed on the box, one fewer container, and one fewer network service — the cheapest attack-surface reduction available here. A donation page that only advertises Bitcoin and Monero has no reason to run `COMPOSE_PROFILES="btc,ltc,ltc-mweb,xmr"`. See [Choosing which assets to run](README.md#choosing-which-assets-to-run). The variable must not be empty, or no wallet containers start at all.

Now edit `.env` and fill in the values. See the [environment variable table](README.md#environment-variables) for what each one does. Skip the variables belonging to assets you did not enable. Generate the passwords you need (`ELECTRUM_RPC_PASSWORD`, and `MONERO_RPC_PASSWORD` / `MONERO_WALLET_PASSWORD` if you run `xmr`) randomly and independently:

```bash
openssl rand -base64 32
```

These are not decorative. The wallet RPCs bind to `0.0.0.0` inside their containers and are reachable by anything else on the Docker network; the RPC passwords are what stand between another container and your wallets.

**Verify:**

```bash
ls -l .env                 # expect -rw------- deploy deploy
git check-ignore -v .env   # expect a match against .gitignore
```

If `git check-ignore` prints nothing, stop and fix `.gitignore` before you ever run `git add`.

**Set `BITCOIN_ELECTRUM_SERVER_ADDRESS` and `LITECOIN_ELECTRUM_SERVER_ADDRESS`** for the Electrum assets you enabled. They are optional, and leaving them blank means Electrum picks public servers at random — those servers then learn which addresses belong to you. Point them at servers you run.

**If you enabled `xmr`, set `MONERO_DAEMON_ADDRESS` to a node you operate.** `docker-compose.yml` passes `--trusted-daemon` unconditionally. That flag is correct for your own node and wrong for a public one: it tells the wallet to rely on data it cannot verify, and it hands the node operator a view of which outputs your wallet cares about.

## 10. First run

```bash
docker compose --env-file .env up -d
docker compose logs -f seed-importer
```

Wait for the four "seed has successfully been imported" messages. Monero will take a while to sync from `MONERO_WALLET_HEIGHT`.

**Verify no ports are published** — the `PORTS` column should be empty for every container:

```bash
docker ps --format 'table {{.Names}}\t{{.Ports}}'
```

**Verify sweeping works.** Send a small amount to a deposit address, then watch:

```bash
docker compose logs -f autoforward
```

You are looking for `Autoforwarded <amount> <COIN> to <address>!`. Confirm the address matches a deposit address in your Kraken account. Do this once with a small amount before you publish any address to donors.

Log rotation is already configured. `docker-compose.yml` caps every service at 10 MB per file and 3 files, so logs cannot fill the disk — 210 MB worst case across all seven containers, which at this workload is months of history. Adjust the `x-logging` block at the top of the file if you want more or less.

**Verify:**

```bash
docker inspect autoforward --format '{{.HostConfig.LogConfig}}'
```

Expect `{json-file map[max-file:3 max-size:10m]}`. An empty map means the container predates the setting and has not been recreated yet; `docker compose up -d` fixes it.

Keep these logs on the box. Do not ship them to a third-party log aggregator — they record your deposit addresses and balances.

## 11. Back up the seeds offline

Write every seed you configured, and `MONERO_WALLET_HEIGHT` if you run `xmr`, on paper or to an encrypted offline volume. Store them somewhere the server cannot reach.

The restore height is easy to overlook and painful to recreate: without it, restoring the Monero wallet means rescanning the chain from the beginning.

Test that a backup actually restores, on a separate machine, before you rely on it.

## 12. Gating deploys

If you use `.github/workflows/deploy.yml`, every secret including your wallet seeds is stored in GitHub and sent to this box on each deploy. Anyone who can push to `main`, edit workflows, or read repository secrets can reach the seeds. Treat push access to this repository as equivalent to access to the wallets.

### Require an approval before anything deploys

The workflow declares `environment: production`, which is the hook GitHub's protection rules attach to. Turning on approvals is a settings change, not a code change.

In **Settings → Environments → production**:

1. Tick **Required reviewers** and add the people or teams who may approve a deploy. Up to six; any one of them can approve. The job pauses and notifies them instead of running.
2. Set **Deployment branches and tags** to **Selected branches** and add `main`. Without this, someone can run the workflow by hand from any branch and the job still receives the production secrets — including a branch whose workflow file they just edited.
3. Optionally set a **Wait timer** so an approved deploy still pauses a few minutes, giving you a window to cancel.

Environment protection rules are free on public repositories. On a private repository they require a paid plan; if `Required reviewers` is greyed out, that is why.

**Verify:** push a trivial commit to `main`. The run should stop at `Review pending` and deploy nothing until someone approves.

### Make the approval mean something

An approval only matters if it binds to specific code. The deploy pins the commit:

```bash
git fetch --quiet origin
git checkout --quiet --detach ${{ github.sha }}
```

This replaced a `git checkout main && git pull`, which resolved the code on the server at execution time. Under the old version, approving a paused run for commit A would deploy commit B if B had landed on `main` while the run waited — unreviewed code shipping under someone else's approval. Keep the pin.

### Close the bypasses

Approvals on the environment do nothing if someone can edit the workflow that references it. In **Settings → Branches**, protect `main`:

- Require a pull request before merging, with at least one approving review.
- Require review from Code Owners, and add a `.github/CODEOWNERS` file so workflow changes need a specific person:

  ```
  /.github/  @your-org/maintainers
  ```

- Dismiss stale approvals when new commits are pushed.
- Include administrators, or the protection is advisory for the people most likely to be targeted.
- Consider requiring signed commits.

Also require 2FA for every member of the organization, and give the workflow's SSH key access to the `deploy` user only, never root.

### Pin the third-party action

`webfactory/ssh-agent@v0.9.0` is pinned to a tag, and a tag can be moved. That action receives the SSH private key for this server. Pin it to a commit SHA instead:

```bash
gh api repos/webfactory/ssh-agent/git/ref/tags/v0.9.0 --jq .object.sha
```

Use the result as `webfactory/ssh-agent@<sha>  # v0.9.0`. Dependabot can keep SHA-pinned actions current if you enable it.

### Set the host key secret

```bash
ssh-keyscan -t ed25519 <server-ip>
```

See [Deploying](README.md#deploying). Deploys fail until this is set, which is the intended behaviour — it is what stops the pipeline from trusting an unknown host on first connection.

### Or keep the seeds out of GitHub entirely

The strongest option is to stop sending secrets through the pipeline. Put them in `.env` on the box, as step 9 describes, and reduce the deploy to:

```yaml
      - name: Deploy
        run: |
          ssh -o StrictHostKeyChecking=yes -o BatchMode=yes ${{ secrets.VPS_USER }}@${{ secrets.VPS_IP }} << 'EOF'
            set -eu
            cd autoforward-autoconvert
            git fetch --quiet origin
            git checkout --quiet --detach ${{ github.sha }}
            docker compose --env-file .env up -d --build
          EOF
```

GitHub then holds only `SSH_PRIVATE_KEY`, `VPS_USER`, `VPS_IP`, and `VPS_SSH_HOST_KEY` — no seeds, no exchange credentials. A compromise of the organization costs you a deploy path, not the wallets. The trade is that configuration changes need an SSH session instead of a secrets page, which is a fair price for a file that changes roughly never.

**Do not run both mechanisms at once.** `docker compose up` already reads `.env` from the working directory, and shell variables take precedence over it. If the workflow sets a variable from a GitHub secret that is empty or missing, the empty value wins over the correct one in `.env` — silently. Pick one source of truth.

---

## Ongoing

**Watch that sweeps keep happening.** A silently stalled autoforward is a security problem, not just an availability one — balances accumulate in the hot wallets, and the small-float assumption this whole design rests on stops holding. Check `docker compose logs --since 24h autoforward` regularly, or alert on the absence of `Autoforwarded` lines.

**Reconcile donations against Kraken deposits** periodically. A stolen seed shows up as donations that arrive at a published address but never reach Kraken. Nothing else in this system will tell you.

**Keep the host updated** beyond unattended-upgrades: `docker compose pull && docker compose up -d --build` after upstream releases, and reboot for kernel updates.

## If you suspect compromise

Assume the seeds are gone. In order:

1. Revoke the Kraken API key immediately, in the Kraken interface.
2. Stop the containers: `docker compose down`.
3. Stop publishing the affected deposit addresses.
4. Generate new seeds on a machine you trust, then follow [Changing seeds](README.md#changing-seeds) — it requires `docker compose down -v` to delete the volumes, since the old wallets persist there otherwise.
5. Rebuild the server from scratch. Do not reuse a box you believe was compromised.
6. Issue a new Kraken API key with the same restricted permissions.

## Gaps this guide cannot close from the host

These are repository-level, listed so you can weigh them rather than be surprised by them:

- **The app container runs as root.** `Dockerfile` sets no `USER`, so the container holding the seeds in its environment runs privileged inside the container namespace. The Electrum containers correctly drop to an unprivileged user.
- **Electrum wallet files are not encrypted at rest.** `seed-importer` restores them without a wallet password, so the key material sits in the Docker volume in the clear. The Monero wallet is encrypted with `MONERO_WALLET_PASSWORD`. Anyone with root on the box, or with access to the underlying disk image, can read the Electrum keys directly — which is why the box must be dedicated and access-controlled.
- **One base image is still unpinned.** `docker/ltc-electrum/Dockerfile` uses `ubuntu:latest`, so a rebuild can pull a different base than the last one did. Everything else is pinned: the Electrum installs by version and SHA-512 checksum, and the Monero wallet RPC by version and image digest. Pinning `ubuntu` to a release digest (`ubuntu:24.04@sha256:...`) would close this.
