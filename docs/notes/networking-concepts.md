# Networking Concepts — Learning Notes

Concepts I learned while building Phase 1, written in my own words.

## An IP belongs to an interface, not to a machine

soc-defender has three interfaces, so three IPs:

| Interface | IP          | Reachable from         |
| --------- | ----------- | ---------------------- |
| `lo`      | 127.0.0.1   | the machine itself     |
| `enp0s3`  | 10.0.2.15   | VirtualBox NAT gateway |
| `enp0s8`  | 10.10.10.20 | Kali on `soclab`       |

Which IP is used depends on which network the connection comes from.

`127.0.0.1` (loopback) always means "the machine I'm typing on": on Windows it's Windows, inside Ubuntu it's Ubuntu.

## VirtualBox network modes

| Mode             | Internet | VMs see each other | Reaches home network     |
| ---------------- | -------- | ------------------ | ------------------------ |
| NAT              | ✅       | ❌ (each VM alone) | ❌                       |
| Internal Network | ❌       | ✅                 | ❌                       |
| Bridged          | ✅       | ✅                 | ✅ (dangerous for a lab) |

## VirtualBox NAT = a software router

In NAT mode, VirtualBox acts like a home router:

- **Default gateway:** `10.0.2.2`
- **DHCP:** gave the VM `10.0.2.15`
- **NAT:** the VM appears to the outside as Windows
- **DNS:** `10.0.2.3`
- **Port forwarding:** my rule `127.0.0.1:2222 → 22`

`ip route` shows `default via 10.0.2.2 dev enp0s3`: all traffic to unknown networks goes to that gateway.

## Every TCP connection has 4 values

```
source IP : source port  →  destination IP : destination port
```

- **Destination port:** fixed, well-known (22 SSH, 80 HTTP, 443 HTTPS)
- **Source port:** random and temporary (ephemeral), so the OS can tell connections apart

With port forwarding there are actually **two** connections, and VirtualBox relays between them:

```
ssh client 127.0.0.1:5xxxx → VirtualBox 127.0.0.1:2222   (on Windows)
VirtualBox 10.0.2.2:61819  → sshd 10.0.2.15:22          (inside NAT network)
```

Ubuntu only sees the second one.

## SSH

Secure Shell: encrypted remote command-line access, client–server, port 22.

1. Client connects to the server on port 22 (TCP)
2. Both agree on an encryption key → everything is encrypted from here
3. The server proves its identity with its host key (fingerprint saved in `known_hosts` on first connection; a changed fingerprint may mean a Man-in-the-Middle)
4. The user authenticates (password or key)
5. The user gets a shell

Syntax: `ssh [options] user@host [command]`

- `user`: an account on the **remote** machine, checked by `sshd` at the end of the path
- `host`: the address I can reach that leads to the target (not always the target's own IP)
- `-p` port, `-i` private key, `-v` verbose (debugging)

Encryption is end-to-end: VirtualBox only relays encrypted bytes.

## Linux permissions (`chmod`)

`r = 4`, `w = 2`, `x = 1`, for owner / group / others.
`600` → owner read+write, nobody else anything → `-rw-------`
## YAML
A human-readable format for configuration files.

**Rules:**
- Every line is `key: value` (no space before the colon)
- **Indentation defines structure**, like Python: deeper lines belong to the line above
- Use **spaces, never Tab** (2 spaces per level by convention)
- Lines at the same indentation level are **siblings**
- `[ ]` is a **list**: `addresses: [10.10.10.20/24]` could hold several IPs

**My netplan file as a tree:**
```
network                           ← root: everything below is network config
├── version = 2                   ← netplan format version (a value, not a container)
└── ethernets                     ← type of interfaces: wired (others: wifis, vlans, bridges)
    └── enp0s8                    ← interface name
        └── addresses = [10.10.10.20/24]
```
`version` and `ethernets` are siblings (both children of `network`), which is why `ethernets` isn't indented under `version`.

**Interface name `enp0s8`:** `en` = ethernet, `p0` = PCI bus 0, `s8` = slot 8 (predictable interface names).

## netplan
Ubuntu's tool for network configuration. It is **declarative**: I describe the state I want ("enp0s8 has this IP"), not the steps to get there.

netplan doesn't manage the network itself, it's a **translator**:
```
YAML files  →  netplan  →  renderer (backend) applies it
```
- **systemd-networkd**: renderer on servers (my case)
- **NetworkManager**: renderer on desktops

**How it reads files:**
- All `.yaml` files in `/etc/netplan/`, in **alphabetical order**, merged together
- On conflict, the **last file wins**
- Number prefixes (`00-`, `60-`) control the order: my `60-soclab.yaml` is read after the installer's `00-installer-config.yaml`

**Commands:**
| Command | What it does |
|---------|--------------|
| `sudo netplan apply` | Apply the configuration |
| `sudo netplan try` | Apply for 120 s, then roll back unless I confirm — safe when editing the network over SSH |

## DNS
Translates names to IPs (`archive.ubuntu.com → 91.189.91.x`). Every `apt update` starts with a DNS query.

A DNS server is a service on an **IP + port 53**. A machine must be given the DNS server's **IP** (not a name — you can't resolve the resolver's name without a resolver), manually or via DHCP.

**Path of one DNS query in my VM:**
```
apt → 127.0.0.53 (systemd-resolved, local)
    → 10.0.2.3   (VirtualBox DNS proxy)
    → Windows DNS (home router / ISP)
    → answer comes back the same way
```
- `resolvectl status`: DNS server per interface (`enp0s3` → 10.0.2.3, `enp0s8` → none, no internet on soclab)
- `resolvectl query ubuntu.com`: resolve a name
- `cat /etc/resolv.conf`: shows `nameserver 127.0.0.53`

**SOC relevance:** DNS logs show every site a host contacts. Traffic to port 53 on an unexpected server is suspicious. DNS spoofing (fake IP for a real name) often goes with ARP spoofing.

## Static IP vs DHCP
DHCP isn't random: it hands out addresses from a defined range, in order.

VirtualBox NAT layout is fixed and identical for every VM:
| IP | Role |
|----|------|
| 10.0.2.2 | Gateway |
| 10.0.2.3 | DNS proxy |
| 10.0.2.15 | First DHCP address → the VM |

**Rule:** machines that others connect to (servers, gateways, DNS) get a **static IP**; machines that only connect out (laptops, phones) use **DHCP**.| `sudo netplan apply` | Apply the configuration |
| `sudo netplan try` | Apply for 120 s, then roll back unless I
