# IPS & Inline Mode — Learning Notes

Concepts from Phase 5, in my own words, with examples. For what was actually done, see [Phase 5 — Suricata as IPS](../phase-5-ips.md).

## IDS vs IPS: it's about where it sits
- **IDS** takes a **copy** of each packet and analyses it. If it matches a rule, it alerts. But the **original packet already reached its destination** — the IDS can't stop it. It sits **beside** the traffic.
- **IPS** sits **in the path** (inline). Every packet passes **through** it; it analyses **before** forwarding, so it can drop a malicious one. It sits **in** the traffic.

> **Example:** the IDS takes a water *sample* from the pipe to test — the water keeps flowing, so even if it finds contamination, the bad water is already through. The IPS is a *valve* in the pipe — every drop passes through it and it can shut instantly.

The deep point: an IDS **cannot block** because it only sees a copy; the original is long gone by the time it decides. An IPS can block because the original waits for its verdict.

## Inline mode
"Inline" = in the line/path of the traffic. **Any IPS must be inline** — you can't block what you only watch a copy of. How it *becomes* inline varies:
- Suricata on Linux (our case): via the firewall (Netfilter) + NFQUEUE.
- A network appliance (pfSense, Cisco): the device is physically in the path already.

So the thing that makes an IPS an IPS is being **inline**, not any specific tool. firewall+NFQUEUE is just *how* we made Suricata inline on Linux.

## The three components that make Suricata inline
Suricata alone only analyses — it has no power to intercept traffic. Three parts cooperate:

1. **Netfilter** — the firewall built into the Linux kernel (Net + filter = network filter). The only thing that can intercept every packet before it reaches its destination. Controlled with `nftables` (or the older `iptables`). The **valve**.
2. **NFQUEUE (Netfilter Queue)** — a Netfilter feature: instead of Netfilter deciding a packet's fate itself, it puts the packet in a **queue** and hands it to an external program. The **bridge**. It exists because Netfilter is simple (allow/deny by address/port) and can't judge "is this an attack?" — that needs an external brain.
3. **Suricata with `-q 0`** — reads the original packets from the queue, analyses with its rules, returns drop/accept. The **brain/guard**.

```
packet → Netfilter (intercepts) → NFQUEUE 0 → Suricata (-q 0, judges) → drop/accept → Netfilter enforces
```
**Roles:** Netfilter intercepts, NFQUEUE hands off, Suricata judges.

> **Example:** a receptionist (Netfilter) handles normal visitors alone. For a suspicious one, he doesn't decide himself — he puts them in a **waiting room** (NFQUEUE) and calls the **security expert** (Suricata) to inspect and decide: enter or be turned away.

## Why the IDS didn't need a firewall but the IPS does
In Phase 3 (IDS) we never touched Netfilter — `af-packet` just read copies off the card. The IPS needs Netfilter because **blocking requires the power to actually intercept a packet**, and that power belongs to Netfilter, not Suricata. Analysis ≠ interception.

## The commands, decoded
```
iifname "enp0s8" queue num 0
```
- `iifname` = **input interface name**: match packets by the card they arrived on. We used `enp0s8` (soclab) only — a **safety choice** so NAT traffic (SSH management) is left untouched and survives if Suricata dies. (`oifname` would match the *output* card.)
- `queue num 0` = send matched packets to NFQUEUE number 0.

```
suricata -c ... -q 0
```
- `-q` = **queue mode**: read from NFQUEUE instead of the card. This is what makes Suricata an IPS.
- `0` = queue number. **Must match** `queue num 0` in the nft rule, or Netfilter queues packets in 0 while Suricata waits at an empty different queue — they never meet.

> **Example:** if reception puts the visitor in **waiting room 0**, the security expert must go to **room 0**. Go to room 1 and he finds no one, while the visitor stays stuck in room 0.

## Why a dropped scan crawls
nmap sends a SYN per port and **waits for a reply** to learn the port's state. With `drop`, Suricata **silently swallows** the packets — nmap gets **no reply at all** (not open, not closed). So it assumes packet loss, waits for a timeout, retransmits, waits longer... for every port. A 0.6s scan became 4+ minutes stuck at 43%.

**Silence is worse for the attacker than rejection.** A rejection (RST) is a fast, clear "no"; silence forces long waits and retries.

**Link to Phase 2:** this is exactly nmap's `filtered` state — no reply = a firewall/IPS eating the packets. Compare `closed` (an active RST reply, "nothing here") vs `filtered` (silence, "something is blocking").

## Proof, side by side (tested)
| | IDS | IPS |
|---|---|---|
| Log | `[**]` alert | `[Drop]` |
| Scan time | 0.6s, completes | 4+ min, stuck |
| Packets | all pass | dropped after threshold |
| Attacker result | sees port 22 open | sees filtered, gets nothing |

## Operational lesson: NFQUEUE is stateful and fragile by hand
Running Suricata manually with `&` in NFQUEUE mode is fragile: a single stuck instance keeps holding queue 0, so new ones fail with `nfq_create_queue failed`. `pgrep` can miss it; `ps aux | grep suricata` finds the real PID. This is why production uses a **persistent service**, not a manual run — the service manages one clean instance and the queue lifecycle.

## Host-based vs network IPS
What we built is **host-based**: Suricata on the defender protects that one host. A **network IPS** is a separate inline device between the attacker and a whole network, protecting everything behind it — that's what pfSense will be later. Same inline principle, different placement and scope.

## Possible interview questions
- Difference between IDS and IPS? IDS watches a copy and alerts (can't block); IPS is inline, sees the original, can drop. The difference is placement (inline) and the action (`alert` vs `drop`).
- What does "inline" mean and why does an IPS need it? In the traffic path; you can't block what you only see a copy of.
- How do you make Suricata an IPS on Linux? Firewall (Netfilter/nftables) queues traffic to NFQUEUE; run Suricata with `-q <n>`; use `drop` rules.
- What is NFQUEUE? A Netfilter feature that queues packets and hands them to an external program to decide — the bridge between the firewall and Suricata.
- Why doesn't the IDS need a firewall but the IPS does? Blocking needs the power to intercept the packet; that's Netfilter's, not Suricata's. The IDS only reads copies.
- What does `-q 0` do, and why must the number match? Puts Suricata in queue mode reading queue 0; it must match the nft `queue num 0` or they never connect.
- Why did `iifname "enp0s8"` matter? It queues only soclab (attack) traffic and leaves NAT/SSH untouched — so a Suricata failure doesn't cut management access.
- Why does a dropped scan become slow? drop gives no reply; nmap waits and retransmits per port. Shows up as `filtered`.
- closed vs filtered (again)? closed = active RST reply; filtered = silence = firewall/IPS dropping.
- Host-based vs network IPS? Host-based protects one machine (Suricata on the host); network IPS is a separate inline device protecting everything behind it (e.g. pfSense).