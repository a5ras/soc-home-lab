# Phase 5 — Suricata as IPS: From Detect to Block

## Goal
In Phase 3, Suricata (IDS) detected the scan but it still **passed** (completed in 0.6s). This phase turns Suricata into an **IPS** that actually **blocks** the attack inline. Full chain + depth: prove the block, map to the attacker's view, note the operational limits.

## IDS vs IPS — the core idea
| | IDS (Phase 3) | IPS (Phase 5) |
|---|---|---|
| Where it sits | beside the traffic | **in the path** (inline) |
| What it sees | a **copy** of each packet (`af-packet`) | the **original** packet |
| Can it block? | no — the original already arrived | yes — the packet waits for its verdict |

> **Example:** an IDS takes a *sample* of the water from the pipe to test in a lab — the water keeps flowing. An IPS is a *valve* in the pipe itself — every drop passes through it and it can shut instantly.

## How Suricata becomes inline: three components
Suricata alone only analyses; it has no power to intercept traffic. Three parts work together:

1. **Netfilter** — the firewall built into the Linux kernel (controlled with `nftables`). The only thing with the power to intercept every packet. The "valve".
2. **NFQUEUE (Netfilter Queue)** — a Netfilter feature that puts packets in a **queue** and hands them to an external program instead of deciding itself. The "bridge".
3. **Suricata with `-q 0`** — reads the original packets from queue 0, analyses them, returns a verdict (drop/accept).

```
packet from Kali → Netfilter (intercepts) → NFQUEUE 0 → Suricata (-q 0, judges)
                                                              ↓
                                                        drop / accept
                                                              ↓
                                                   Netfilter enforces it
```
Roles in one line: **Netfilter intercepts, NFQUEUE hands off, Suricata judges.**

Note: the IDS never used Netfilter (`af-packet` read copies). The IPS needs it, because blocking requires the power to actually intercept the packet — which Netfilter has and Suricata doesn't.

## Step 0 — Snapshot first
Editing the firewall and packet path can cut the defender off from itself (including the SSH session). Took a VM snapshot `before-ips` before starting.

## Step 1 — Build the gate (nftables rule)
```bash
sudo nft add table inet suricata_ips
sudo nft add chain inet suricata_ips input '{ type filter hook input priority 0; }'
sudo nft add rule inet suricata_ips input iifname "enp0s8" queue num 0
```
- `iifname "enp0s8"` = **input interface name**: match only packets arriving on the soclab card. **Safety choice:** NAT traffic (`enp0s3`, where SSH comes in) is left untouched, so if Suricata dies the SSH session survives.
- `queue num 0` = send matched packets to NFQUEUE 0.

**Warning:** once this rule exists, soclab packets go to queue 0, but until Suricata reads that queue, packets with no reader are **dropped** — soclab traffic is cut until the next step. Normal and temporary.

## Step 2 — Run Suricata in IPS mode
```bash
sudo systemctl stop suricata            # stop the IDS (af-packet) service
sudo suricata -c /etc/suricata/suricata.yaml -q 0 &
```
`-q 0` = **queue mode, queue 0**: read original packets from NFQUEUE 0 instead of the card. This is what makes it an IPS. The `0` must match `queue num 0` in the nftables rule, or they never meet.

Verified traffic flows again: `ping 10.10.10.20` from Kali succeeded — Suricata receives each packet, sees it's clean, forwards it.

## Step 3 — Switch the rule from alert to drop
```bash
sudo nano /var/lib/suricata/rules/local.rules
# change the first word: alert → drop
drop tcp any any -> $HOME_NET any (msg:"LOCAL Nmap TCP scan detected"; flow:to_server; flags:S+; threshold:type both, track by_src, count 15, seconds 10; sid:1000001; rev:3;)
```
`alert` = detect and warn; `drop` = detect **and block**. Only the first word changes.

## Step 4 — Attack and prove the block
```bash
# defender
sudo tail -f /var/log/suricata/fast.log
# Kali
sudo nmap -sS -p 1-1000 10.10.10.20
```

**Defender side** — the log now shows `[Drop]`, not just an alert:
```
[Drop] [1:1000001:3] LOCAL Nmap TCP scan detected {TCP} 10.10.10.10 -> 10.10.10.20:5900
```

**Attacker side** — the scan crawled:
```
0:04:30 elapsed ... About 43.24% done; ETC: (0:05:56 remaining)
```
A scan that finished in **0.6s** as IDS now took **4+ minutes stuck at 43%**.

### Why the scan crawls
nmap sends a SYN and **waits for a reply** to learn a port's state. With `drop`, Suricata **silently swallows** the packets — nmap gets **no reply** (not open, not closed), so it assumes loss, waits (timeout), and retransmits, over and over. Silence is worse for the attacker than rejection.

**Link to Phase 2:** this is exactly `filtered` in nmap — no reply = a firewall/IPS eating the packets (vs `closed`, which replies with an active RST).

## Full comparison (tested)
| | IDS (Phase 3) | IPS (Phase 5) |
|---|---|---|
| In the log | `[**]` alert | `[Drop]` |
| The scan | completes in 0.6s | crawls 4+ min, stuck |
| Packets | all pass | dropped after threshold |
| Attacker gets | the info (port 22 open) | nothing useful (filtered) |

## Problems & Fixes
- **`nfq_create_queue failed` / `nfq thread failed to initialize`**
  Cause: an old Suricata instance was still holding queue 0, so a new one couldn't open it. `pgrep` missed it; `ps aux | grep suricata` revealed the stuck PID.
  Fix: `sudo kill -9 <pid>` the real process (and its sudo wrappers), confirm with `ps aux | grep suricata`, then restart. Lesson: in NFQUEUE mode, one stuck instance blocks everything — a persistent service is cleaner than the manual `&` run.

- **Soclab traffic cut after adding the nft rule**
  Cause: packets queued to NFQUEUE 0 with no reader are dropped.
  Fix: start Suricata with `-q 0` immediately after the rule.

## Teardown (returned to stable IDS)
The manual `&` run and in-memory nft rule are fragile/temporary. After proving the IPS works, returned to the stable IDS setup for the next phases:
```bash
sudo pkill -9 suricata
sudo nft delete table inet suricata_ips      # remove the gate
sudo systemctl start suricata                # back to af-packet IDS
# and reverted the rule: drop → alert
```
A persistent IPS service can be set up later; the IPS behaviour is proven and documented.

## Note on architecture (for later)
This is a **host-based** IPS (Suricata on the defender itself, protects this host). The alternative — a **separate inline device** between attacker and the rest of the network, protecting everything behind it — is what **pfSense** will provide in a later phase. Same principle (inline), different placement.

## Screenshots
- [ ] `fast.log` showing `[Drop]` during the scan
- [ ] nmap on Kali crawling (4+ min, stuck at ~43%) vs 0.6s before
- [ ] `nft list ruleset` showing the queue rule