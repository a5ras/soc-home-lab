# Phase 1 — Environment Setup

## Goal

Build an isolated lab where the attacker (Kali) and the defender (Ubuntu Server) can reach each other, without touching my home network.

## Host constraints

- Windows host, 8 GB RAM → max 2 VMs running at the same time
- RAM split: Kali 3 GB, soc-defender 1.5 GB (→ 2 GB when Suricata is added), ~3.5 GB left for Windows

## soc-defender VM

| Setting  | Value                        |
| -------- | ---------------------------- |
| OS       | Ubuntu Server 26.04.1 LTS    |
| RAM      | 1536 MB                      |
| CPU      | 2                            |
| Disk     | 20 GB, dynamically allocated |
| Hostname | soc-defender                 |

**Why Ubuntu Server (no GUI):** lightweight, and real servers are managed from the command line.

**Why OpenSSH enabled:** to manage the defender remotely, like real servers.

**Storage:** the installer used LVM by default → partitions can be extended later if logs fill the disk.

## Network design

| VM           | Adapter   | Mode                        | Interface | IP                   | Purpose                          |
| ------------ | --------- | --------------------------- | --------- | -------------------- | -------------------------------- |
| soc-defender | Adapter 1 | NAT                         | `enp0s3`  | 10.0.2.15 (DHCP)     | Internet access for updates only |
| soc-defender | Adapter 2 | Internal Network (`soclab`) | `enp0s8`  | 10.10.10.20 (static) | Isolated lab network for attacks |
| Kali         | Adapter 1 | NAT                         | `eth0`    | 10.0.2.15 (DHCP)     | Internet access for updates only |
| Kali         | Adapter 2 | Internal Network (`soclab`) | `eth1`    | 10.10.10.10 (static) | Isolated lab network for attacks |

Both VMs show `10.0.2.15` on NAT without conflict: in VirtualBox, each VM has its own separate NAT network.

**Why Internal Network and not Bridged:** Bridged puts the VM on my real home network, so attacks could reach real devices. Internal Network keeps all traffic between the lab VMs only. (Kali's Adapter 1 was originally Bridged; I switched it to NAT for this reason.)

**Why not NAT only:** in VirtualBox NAT mode each VM sits alone in its own private network, so Kali and the defender can't see each other. NAT is kept only for internet access.

### IP plan

| IP          | Host                                  |
| ----------- | ------------------------------------- |
| 10.10.10.1  | Reserved for pfSense (gateway, later) |
| 10.10.10.10 | Kali (attacker)                       |
| 10.10.10.20 | soc-defender                          |
| 10.10.10.30 | Reserved for Wazuh (later)            |

**Why 10.10.10.0/24:** private range (RFC 1918) that doesn't collide with my home network (192.168.x.x), VirtualBox NAT (10.0.2.x) or Kali's Docker bridges (172.x.x.x), which would cause routing confusion.

## soc-defender: static IP with netplan

File: `/etc/netplan/60-soclab.yaml`

```yaml
network:
  version: 2
  ethernets:
    enp0s8:
      addresses: [10.10.10.20/24]
```

```bash
sudo chmod 600 /etc/netplan/60-soclab.yaml
sudo netplan apply
ip a show enp0s8
```

- **Why a separate file:** netplan reads every `.yaml` in `/etc/netplan/` in alphabetical order. The installer already created `00-installer-config.yaml`; `60-` is read after it, and I don't modify the installer's file.
- **Why `chmod 600`:** netplan files may contain secrets (Wi-Fi passwords, VPN keys), so only root should read them.
- **Why static:** the target must stay the same between sessions, and logs and detection rules will rely on these addresses.
- **Proof it works:** `enp0s8` shows `inet 10.10.10.20/24` with `valid_lft forever` and no `dynamic` flag (unlike `enp0s3`, which got its IP from DHCP).

## Kali: static IP with NetworkManager

Kali uses **NetworkManager** (not netplan), configured with `nmcli`.

```bash
# Bind the auto-created DHCP profile to eth0 (NAT) only, then apply it
sudo nmcli con modify "Wired connection 1" connection.interface-name eth0
sudo nmcli con up "Wired connection 1"

# Create a static profile for eth1 (soclab), then apply it
sudo nmcli con add type ethernet ifname eth1 con-name soclab ipv4.method manual ipv4.addresses 10.10.10.10/24
sudo nmcli con up soclab
```

| Device | Connection         | IP          | Type               |
| ------ | ------------------ | ----------- | ------------------ |
| eth0   | Wired connection 1 | 10.0.2.15   | `dynamic` (DHCP)   |
| eth1   | soclab             | 10.10.10.10 | `forever` (static) |

Details on how NetworkManager works: [notes/kali-networkmanager.md](notes/kali-networkmanager.md)

## Management access from Windows (SSH + port forwarding)

Windows can't reach the defender directly: it isn't on `soclab`, and NAT only allows traffic out of the VM. So I added a port forwarding rule on the defender's Adapter 1 (NAT):

| Name | Protocol | Host IP   | Host port | Guest port |
| ---- | -------- | --------- | --------- | ---------- |
| ssh  | TCP      | 127.0.0.1 | 2222      | 22         |

```bash
ssh -p 2222 a5rasx@127.0.0.1
```

- Host IP is `127.0.0.1` so the port is only open to my own machine, not my home network.
- The VM can now run headless; I manage it from Windows Terminal (bigger font, copy/paste works).
- **Management access vs lab traffic:** I manage the VM through NAT, and attacks happen on `soclab`. Separating the two is common practice in real networks.

## Verification

### Connectivity tests from Kali

| Command                 | Tests                           | Result                      |
| ----------------------- | ------------------------------- | --------------------------- |
| `ping -c 2 8.8.8.8`     | Internet by IP (eth0 + routing) | ✅                          |
| `ping -c 2 google.com`  | DNS                             | ✅                          |
| `ping -c 4 10.10.10.20` | soclab link to the defender     | ✅ 0% loss, `ttl=64`, ~2 ms |

`ttl=64` unchanged → direct link, no router between the VMs.

### Same sshd, two different doors

```
# From Windows (through NAT port forwarding)
$ echo $SSH_CONNECTION
10.0.2.2 61819 10.0.2.15 22

# From Kali (directly on soclab)
$ echo $SSH_CONNECTION
10.10.10.10 55312 10.10.10.20 22
```

- From Windows, the connection comes from `10.0.2.2` (VirtualBox NAT gateway) and enters through `enp0s3`.
- From Kali, it comes from `10.10.10.10` and enters through `enp0s8`.
- sshd also logs the source: `Last login: ... from 10.0.2.2`, the first log I read in this project.

### Snapshots

- [ ] `phase-1-complete` taken for both VMs

## Problems & Fixes

- **`bash: $'\302\226cd': command not found` in Git Bash**
  Cause: switching keyboard layout (Alt+Shift) inside the terminal inserted an invisible character.
  Fix: Ctrl+C for a clean line, switch layout before clicking in the terminal (or use Win+Space).

- **`git push` rejected (fetch first)**
  Cause: I edited a file directly on GitHub, so the remote had a commit my local repo didn't have.
  Fix: `git pull --rebase` then `git push`. Rule: always `git pull` before starting work.

- **Almost saved the netplan file in the wrong place**
  Cause: typed `etc/netplan/...` (relative path, resolves inside my home folder) instead of `/etc/netplan/...` (absolute path).
  Fix: reopened with `sudo nano /etc/netplan/60-soclab.yaml`.

- **`who` returns nothing on Ubuntu 26.04**
  Cause: recent Ubuntu no longer records sessions in `/var/run/utmp`, which `who` reads.
  Fix: use `echo $SSH_CONNECTION` or `ss -tn` to see the current connection.

- **Kali: no internet after switching Adapter 1 to NAT**
  Cause: NetworkManager's auto profile `Wired connection 1` wasn't bound to a device, so it was applied to eth1 (soclab), which has no DHCP server and stayed stuck on "getting IP configuration". eth0 (NAT) had no profile at all.
  Fix: bound the profile to eth0 and created a separate static profile for eth1.

- **`Destination Host Unreachable` from Kali to 10.10.10.20**
  Cause: the defender VM was powered off, so Kali's ARP request ("who has 10.10.10.20?") got no reply.
  Fix: started the defender. Lesson: check the simplest cause first.

- **Ran `nmtui` on the defender by mistake**
  Cause: I was inside an SSH session on soc-defender, not on Kali. Ubuntu Server uses netplan + systemd-networkd, not NetworkManager.
  Lesson: always check the prompt (`user@host`) before running a command.

- **`dpkg was interrupted` on soc-defender**
  Cause: a package installation was interrupted (VM shutdown or cancelled updates during install). Every future install would fail.
  Fix: `sudo dpkg --configure -a`, then `sudo apt update && sudo apt upgrade -y`.
