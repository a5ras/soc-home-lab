# Phase 1 — Environment Setup

## Goal
Build an isolated lab where the attacker (Kali) and the defender (Ubuntu Server) can reach each other, without touching my home network.

## Host constraints
- Windows host, 8 GB RAM → max 2 VMs running at the same time
- RAM split: Kali 3 GB, soc-defender 1.5 GB (→ 2 GB when Suricata is added), ~3.5 GB left for Windows

## soc-defender VM
| Setting  | Value                        |
|----------|------------------------------|
| OS       | Ubuntu Server 26.04.1 LTS    |
| RAM      | 1536 MB                      |
| CPU      | 2                            |
| Disk     | 20 GB, dynamically allocated |
| Hostname | soc-defender                 |

**Why Ubuntu Server (no GUI):** lightweight, and real servers are managed from the command line.

**Why OpenSSH enabled:** to manage the defender remotely from Kali, like real servers.

**Storage:** the installer used LVM by default → partitions can be extended later if logs fill the disk.

## Network design
| Adapter   | Mode                        | Purpose                          |
|-----------|-----------------------------|----------------------------------|
| Adapter 1 | NAT                         | Internet access for updates only |
| Adapter 2 | Internal Network (`soclab`) | Isolated lab network for attacks |

**Why Internal Network and not Bridged:** Bridged puts the VM on my real home network, so attacks could reach real devices. Internal Network keeps all traffic between the lab VMs only.
**Why not NAT only:** in VirtualBox NAT mode each VM sits alone in its own private network, so Kali and the defender can't see each other. NAT is kept only for internet access.
