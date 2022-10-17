# Monero autoforward and autoconvert

These steps will allow you to set up a simple Monero wallet program that will automatically forward all received contents to another Monero wallet address. This is useful if you receive XMR with BTCPay Server and need to forward it to a static exchange address to sell. There is another cron job to autoconvert with Kraken.

## High level process

This is intended to run on Ubuntu/Linux.

The high-level process is:

1. Create/transfer a Monero wallet file
2. Run Monero Wallet RPC on the server
3. Set up a cron job to autoforward every X minutes
4. Set up a cron job to autoconvert every X minutes

## Prerequisities

### Spare server; can be super low spec

Basically any VPS will do. Do yourself a favor and use an SSD though. If you are using this for a critical production deployment, consider 2+ CPUs for faster scanning.

### Installed latest [Monero CLI tools](https://getmonero.org/downloads/#cli)

You'll need monero-wallet-rpc, and possibly monero-wallet-cli.

### Installed Docker

```
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y ufw curl
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
su - $USER
```

### Hardened Firewall

Keep the bad guys out.

```
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow ssh
sudo ufw enable
```

### For autoconvert: Kraken account

We recommend creating an [additional Kraken account](https://support.kraken.com/hc/en-us/articles/360001214163-Can-I-create-multiple-accounts-). This cron job will autoconvert all balances in this account to the specific asset.

You can optionally use an exchange that supports auto-convert functionality, for example one that auto converts XMR deposited into an address to USDC.

## Create/transfer a Monero wallet file

If you already have a Monero wallet file, then skip these steps and simply transfer your wallet file over to the server instead.

`monero-wallet-cli`

Create a new wallet name that you'll remember, such as `forwarder`. Choose a STRONG password, though if this box is compromised, people can steal any funds that are in the wallet at that point and any point in the future.

Make sure the wallet file is chmod 700

## Run Monero Wallet RPC on the server

We will use [Seth's](https://sethforprivacy.com) `simple-monero-wallet-rpc` Docker image. This will allow it to auto update and restart without any further modifications.

Change `<RPCPASSWORD>`, `<FILE>` (use the .keys file), and `<PASSWORD>`. Optionally change the daemon address to your own daemon.

```
docker run -d --restart unless-stopped --name="monero-wallet-rpc" -p 18081:18081 -v bitmonero:/home/monero sethsimmons/simple-monero-wallet-rpc:latest --rpc-bind-port=18081 --daemon-address=xmr-node.cakewallet.com:18081 --wallet-file=<FILE> --password=<PASSWORD> --rpc-login=monero:<RPCPASSWORD>
docker run -d \
    --name watchtower --restart unless-stopped \
    -v /var/run/docker.sock:/var/run/docker.sock \
    containrrr/watchtower --cleanup
```

Confirm monero-wallet-rpc is started correctly by checking the logs: `docker logs --follow monero-wallet-rpc`

NOTE: I had issues using Seth's docker image. It was unable to find the wallet file. I was able to run `monero-wallet-rpc` with this command to work: `./monero-wallet-rpc --rpc-bind-port=18081 --daemon-address=xmr-node.cakewallet.com:18081 --wallet-file=<FILE> --password=<PASSWORD> --rpc-login=monero:<RPCPASSWORD> --detach`

## Set up a cron job to autoforward every X minutes

First, decide how often you want the command to run. If you want to only forward occasionally, then setting it to every 60 minutes or even 24 hours may be fine. If you want the fastest performance, setting up forwarding every minute is reasonable.

Calculate the necessary operation for timings using [this website](https://crontab.guru). Here are some common ones:

```
*/5 * * * *`           every 5 minutes
0 */1 * * *`           every 1 hour
0 0 * * */1`           every 1 day
```

Save `monero-autoforward.py`. Make sure to change the address, password, and (if needed) index.

Set up the cron function to run this command.

`crontab -e`

 Append the following job:
 
 `*/5 * * * * /usr/bin/python3 /home/$USER/monero-forwarder.py`
 
 Save the file.
 
 `sudo systemctl enable cron.service`
 
 You're done! The cron task will run every 5 minutes, or whatever other duration you specified.
 
 ## Set up a cron job to autoconvert every X minutes
 
 This uses Kraken. If you want to write a python script for another exchange, then we're happy to add it here!
 
 TODO

# Credits

Thanks to [Seth](https://sethforprivacy.com) for their docker image, and the initial instructions about Monero node/service hardening.
