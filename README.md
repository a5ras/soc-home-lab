# soc-home-lab

Hands-on SOC home lab, built and documented from scratch: attack from Kali, detect with
Suricata (and later Wazuh), defend, and write up every step — including the detection
rules and the reasoning behind them.

## Goal

Learn blue-team / SOC fundamentals by living them rather than reading about them. Each
phase follows the same loop: **run a real attack → check whether the ordinary tools
notice → put the right sensor on the network → write a detection rule → catch it →
defend, and prove the defence.** Every phase has a full write-up and a separate
"learning notes" file explaining the concepts in plain language.

## Lab architecture

Three VirtualBox VMs on a single Windows host (8 GB RAM), kept on an **isolated internal
network** so no attack can ever reach the real home network.

| VM               | Role                         | soclab IP     | Key software                     |
| ---------------- | ---------------------------- | ------------- | -------------------------------- |
| Kali             | Attacker                     | `10.10.10.10` | nmap, arpspoof, scapy            |
| soc-defender     | Defender / monitor (Ubuntu Server) | `10.10.10.20` | Suricata (IDS/IPS), arpwatch, nftables |
| Metasploitable 2 | Victim (vulnerable by design) | `10.10.10.30` | —                                |

### Network

- **`soclab` — Internal Network `10.10.10.0/24`:** the isolated lab segment where all
  attacks happen. VMs can see each other here, but it has no route to the internet or
  the home network.
- **NAT (per VM):** a second adapter used only for internet access (updates). In
  VirtualBox NAT mode each VM is alone in its own private network, so the lab traffic
  stays on `soclab`.
- **Management:** the defender runs headless and is managed over SSH from Windows via a
  NAT port-forward (`127.0.0.1:2222 → 22`), keeping management traffic separate from lab
  traffic.

### IP plan

| IP            | Host                                      |
| ------------- | ----------------------------------------- |
| `10.10.10.1`  | Reserved for pfSense gateway (later)      |
| `10.10.10.10` | Kali (attacker)                           |
| `10.10.10.20` | soc-defender                              |
| `10.10.10.30` | Metasploitable 2 (victim)                 |
| Wazuh         | To be assigned in Phase 6                 |

**Why `10.10.10.0/24`:** a private (RFC 1918) range chosen so it doesn't collide with the
home network, VirtualBox NAT (`10.0.2.x`) or Docker bridges (`172.x`).

## Tools

- **Attack:** Kali Linux — nmap (port scanning), arpspoof (ARP cache poisoning), scapy
  (custom packet crafting).
- **Detect / defend:** Suricata (IDS and inline IPS via Netfilter/NFQUEUE), arpwatch
  (stateful ARP monitoring), nftables, static ARP entries.
- **Infrastructure:** VirtualBox, Ubuntu Server (netplan + systemd-networkd), Kali
  (NetworkManager), Metasploitable 2.
- **Planned:** Wazuh (SIEM), pfSense (network IPS/gateway), a honeypot.

## Phases

| Phase | Focus                                               | Status      | Documentation                                     |
| ----- | --------------------------------------------------- | ----------- | ------------------------------------------------- |
| 1     | Environment setup (VMs, isolated network, static IPs, SSH) | Done        | [phase-1-setup.md](docs/phase-1-setup.md)         |
| 2     | Port scan & why `auth.log` is blind to it           | Done        | [phase-2-portscan.md](docs/phase-2-portscan.md)   |
| 3     | Suricata as IDS — custom rule catches the scan      | Done        | [phase-3-suricata.md](docs/phase-3-suricata.md)   |
| 4     | ARP spoofing — attack, detect, defend, evade        | Done        | [phase-4-arp-spoofing.md](docs/phase-4-arp-spoofing.md) |
| 5     | Suricata as IPS — from detect to block (inline)     | Done        | [phase-5-ips.md](docs/phase-5-ips.md)             |
| 6     | Wazuh SIEM                                           | Planned     | —                                                 |
| 7     | More attacks, honeypot, final documentation         | Planned     | —                                                 |

## Concept notes

Each phase has a companion file explaining the underlying concepts in plain language:

- [networking-concepts.md](docs/notes/networking-concepts.md) — IPs, interfaces,
  VirtualBox modes, TCP connections, SSH, YAML/netplan (Phase 1)
- [kali-networkmanager.md](docs/notes/kali-networkmanager.md) — NetworkManager, devices
  vs. connections, diagnosing connectivity (Phase 1)
- [portscan-concepts.md](docs/notes/portscan-concepts.md) — `ss`, ARP, `auth.log`,
  network layers (Phase 2)
- [ids-suricata-concepts.md](docs/notes/ids-suricata-concepts.md) — how an IDS works,
  anatomy of a detection rule, Suricata logs (Phase 3)
- [arp-spoofing-concepts.md](docs/notes/arp-spoofing-concepts.md) — ARP, MITM,
  detection types and their blind spots (Phase 4)
- [ips-concepts.md](docs/notes/ips-concepts.md) — IDS vs. IPS, inline mode,
  Netfilter + NFQUEUE (Phase 5)
