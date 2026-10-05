# Phase 4 — ARP Spoofing: Attack, Detect, Defend

## Goal
Run a Layer 2 attack (ARP spoofing / MITM), prove it, detect it, defend against it, and prove the defence. Full chain, including the depth layer: evasion-awareness, MITRE mapping, and detection quality.

**MITRE ATT&CK:** T1557.002 — Adversary-in-the-Middle: ARP Cache Poisoning.

## Lab setup
A third VM was added to make a realistic MITM scenario (needs a victim, a target, and an attacker in the middle).

| VM | Role | IP | Notes |
|----|------|-----|-------|
| Kali | attacker (MITM) | 10.10.10.10 | eth1 on soclab |
| soc-defender | victim / monitor | 10.10.10.20 | Suricata + arpwatch |
| Metasploitable 2 | victim (impersonated) | 10.10.10.30 | vulnerable-by-design, soclab only, **no NAT** |

Metasploitable uses the old network system (`/etc/network/interfaces`, static IP), vs netplan on the defender and NetworkManager on Kali — three eras of Linux networking, same goal.

## Step 1 — The attack (Kali)
Enable forwarding so intercepted traffic is relayed (MITM, not DoS):
```bash
sudo sysctl -w net.ipv4.ip_forward=1
```
Poison both directions (two terminals, one per direction):
```bash
# tell the defender: "I (Kali's MAC) am 10.10.10.30"
sudo arpspoof -i eth1 -t 10.10.10.20 10.10.10.30
# tell Metasploitable: "I (Kali's MAC) am 10.10.10.20"
sudo arpspoof -i eth1 -t 10.10.10.30 10.10.10.20
```
`-t <IP>` = the victim whose table we poison; the trailing `<IP>` = the identity we impersonate. Each window streams `arp reply ... is-at <Kali MAC>` continuously, because the real ARP table self-heals and must be constantly re-poisoned.

## Step 2 — Proof the attack worked (defender)
```bash
ip neigh
```
Before:
```
10.10.10.30 ... lladdr 08:00:27:33:64:b7   ← Metasploitable's real MAC
```
During the attack:
```
10.10.10.30 ... lladdr 08:00:27:77:e4:f8   ← now Kali's MAC!
10.10.10.10 ... lladdr 08:00:27:77:e4:f8 STALE   ← Kali's real identity, now idle
```
**Signature of poisoning: two different IPs pointing to the same MAC.**

## Step 3 — Detection attempt 1: Suricata (a useful failure)
Watching `fast.log` during the attack showed **nothing**. ARP lives at the Link layer and carries no IP; Suricata was set to watch IP traffic, so ARP passed under its radar.

Enabling ARP logging (`eve-log: - arp: enabled: yes`) made Suricata **log** ARP events (confirmed ~57 events, one read in full showed the lie clearly). But trying to write a detection rule failed:
```
Error: protocol "arp" cannot be used in a signature
```
**Finding: Suricata 8 logs ARP but does not support ARP detection rules in practice.** A real tool limit, discovered by testing, not guessing.

## Step 4 — Detection attempt 2: arpwatch (the right tool)
arpwatch keeps a reference IP→MAC table and alerts when a binding changes — exactly what a stateless IDS rule can't do.

```bash
# prepare a clean data file
sudo mkdir -p /var/lib/arpwatch
sudo touch /var/lib/arpwatch/arp.dat
# run it in the background, silently, on soclab
sudo nohup arpwatch -i enp0s8 -f /var/lib/arpwatch/arp.dat -N > /dev/null 2>&1 &
pgrep arpwatch        # confirm it's alive
```

**Order matters:** teach it the clean state first, then attack. First run it learned the *poisoned* state as normal and saw nothing. Correct sequence:
1. Stop the attack, let the network heal.
2. Clear arpwatch's data, start it, ping both hosts so it learns the **real** MACs (`new station 10.10.10.30 08:00:27:33:64:b7`).
3. Start the attack.

During the attack, arpwatch alerted (in `/var/log/syslog`):
```
changed ethernet address 10.10.10.30 08:00:27:77:e4:f8 (08:00:27:33:64:b7)
ethernet mismatch 10.10.10.30 08:00:27:77:e4:f8 (08:00:27:33:64:b7)
flip flop 10.10.10.30 08:00:27:33:64:b7 (08:00:27:77:e4:f8)
```
Reads as: `.30` was at `...33:64:b7`, now claims `...77:e4:f8` (Kali). Three alert types, all ARP-spoofing fingerprints: the MAC **changed**, a packet **mismatches** the record, the binding **flip-flops**.

Note: arpwatch notices the change when ARP traffic carrying the new binding passes — a `ping 10.10.10.30` from the defender forced the update and triggered it.

## Step 5 — Defence: static ARP entry
Lock the real binding so no ARP reply can change it:
```bash
sudo ip neigh replace 10.10.10.30 lladdr 08:00:27:33:64:b7 dev enp0s8 nud permanent
ip neigh show 10.10.10.30     # now shows PERMANENT
```
`nud permanent` = the entry never expires and ignores all ARP updates. A normal entry auto-updates on any ARP reply (the vulnerability); a permanent one refuses them.

## Step 6 — Prove the defence (and find its limit)
With the attack running again:
```bash
ip neigh show 10.10.10.30     # stays 08:00:27:33:64:b7 PERMANENT — the lie is rejected
```
The defender's table **held**. But a `ping 10.10.10.30` during the attack **failed (100% loss)**.

**Why — the real lesson:** I only locked the **defender's** table. Kali was still poisoning the **other direction** and intercepting the return path. The defender sent correctly, but the reply path was still disrupted. After stopping the attack, the ping succeeded again, confirming the defence worked and the failure was the ongoing interception.

**Takeaway: one-sided static ARP protects that host's table but not a two-way conversation. Real protection needs static entries on all sensitive hosts, or a network-level solution.**

## Defence, properly done
- **static ARP entries:** work, but don't scale (imagine 500 hosts, each needing manual entries updated on every change). Used only for critical hosts (gateway, servers). Also note: the entry above is in-memory and is lost on reboot — making it persistent needs a boot-time config.
- **Dynamic ARP Inspection (DAI):** the enterprise answer, enforced on managed switches.

## Detection quality (depth layer)
The poisoning signature (one MAC on several IPs) is an **indicator**, not proof: rare legitimate cases exist (a router/host with several IPs). A real analyst confirms with corroborating evidence (a flood of unsolicited ARP replies, a flip-flop) before declaring an attack — the difference between a false positive and a true positive.

## Full chain summary
| Stage | Result |
|-------|--------|
| Attack | ARP spoof both directions, ip_forward for MITM |
| Prove | `ip neigh`: `.30` → Kali's MAC; one MAC on two IPs |
| Detect (general) | Suricata can't — no ARP rule support |
| Detect (specialist) | arpwatch: changed/mismatch/flip-flop |
| Defend | static ARP `PERMANENT` rejected the lie |
| Prove defence + limit | table held; one-sided defence doesn't protect a two-way path |

## Screenshots
- [ ] `ip neigh` before vs during attack (`.30` flips to Kali's MAC)
- [ ] arpwatch `changed ethernet address` / `flip flop` in syslog
- [ ] `ip neigh show 10.10.10.30` = PERMANENT during attack (defence holds)