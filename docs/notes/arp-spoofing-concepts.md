# ARP Spoofing — Learning Notes

Concepts from Phase 4, in my own words, with examples. For what was actually done, see [Phase 4 — ARP Spoofing](../phase-4-arp-spoofing.md).

## Why ARP exists
Inside one local network, machines don't actually talk by **IP** — they talk by **MAC address**.

- **IP** is a *logical* address: changeable, used to route between networks.
- **MAC** is a *physical* address: burned into the network card, used for actual delivery on the local wire.

Programs know the destination by IP ("send to 10.10.10.30"), but physical delivery needs the MAC. **ARP is the bridge that translates IP → MAC.** Without it, a machine knows which IP it wants but not which physical card to hand the packet to.

How it works:
```
1. Defender broadcasts: "who has 10.10.10.30? send me its MAC"   ← ARP request
2. Only the owner replies: "me, my MAC is 08:00:27:33:64:b7"     ← ARP reply
3. Defender caches the IP→MAC mapping in its ARP table
```
That table is what `ip neigh` shows.

## The naivety that makes the attack possible
Two design flaws in ARP:

1. **No authentication.** When an ARP reply arrives ("I own this IP, my MAC is X"), the machine **believes it immediately** and updates its table — no signature, no password, no verification.
2. **Accepts unsolicited replies (gratuitous ARP).** Most systems accept an ARP reply even if they never asked. So the attacker doesn't wait for a question — it just sends lies, and machines swallow them.

> **Example:** ARP is like shouting in a room "who is Ahmed?". Ahmed raises his hand — but nothing stops an impostor from raising his too, with no ID check, so you hand him your message.

## The attack: becoming the Man-in-the-Middle
The attacker (Kali, .10) sends **two lies**, one to each victim:
```
to the defender (.20):      "I am 10.10.10.30, my MAC is Kali's MAC"
to Metasploitable (.30):    "I am 10.10.10.20, my MAC is Kali's MAC"
```
Now each victim sends to the other via Kali. Kali sits **in the middle** of their traffic — **Man-in-the-Middle (MITM)**.

> **Example:** a con-man tells both you and your friend "I'm the new postman, give me your letters". Every message passes through him: he reads it, maybe changes it, then forwards it. Neither of you notices.

**Why two directions (two terminals):** one lie captures only traffic *to* the target; the replies go direct. Both lies make both directions pass through Kali — the full conversation.

**Why it runs continuously:** the real ARP table self-heals (the real devices also send correct replies), so a single lie would be corrected in seconds. The attacker must keep flooding the lie.

## Why the attacker keeps its OWN table clean (my question)
Kali poisons the **victims'** tables but keeps its **own** ARP table correct. So Kali alone knows the true map of the network:
```
10.10.10.20 → defender's real MAC
10.10.10.30 → Metasploitable's real MAC
```
This is what lets it relay: when a packet for .30 arrives, Kali looks in its *correct* table and forwards to the real Metasploitable. If the attacker poisoned itself too, it would loop / break and the attack would collapse instantly. Keeping its own table clean is what makes the MITM work and stay silent.

> **Example:** the con-man gave both sides his address, but keeps their **real** addresses in his pocket, so he can actually deliver the letters after reading them.

## ip_forward — spy vs cut
When a packet arrives at Kali addressed to .30 (not to Kali), the default behaviour is "not mine → drop it". That breaks the connection = **DoS**, not spying.

```bash
sudo sysctl -w net.ipv4.ip_forward=1
```
This tells Kali: "if a packet isn't for you, don't drop it — **forward** it to its real destination." Kali becomes a relay (acts like a router): receives → reads/logs (the spying) → forwards. The connection continues, nobody notices.

| Part | Meaning |
|------|---------|
| `sysctl` | read/change kernel settings at runtime |
| `-w` | write a value (temporary, lost on reboot) |
| `net.ipv4.ip_forward=1` | 1 = forward other hosts' packets (default 0) |

**ip_forward is the difference between MITM (spy) and DoS (cut).** It's also a legitimate feature (routers, firewalls use it) — an attack tool is often just a normal system function misused.

## Reading the attack: the arpspoof command
```bash
sudo arpspoof -i eth1 -t 10.10.10.20 10.10.10.30
```
| Part | Meaning |
|------|---------|
| `-i eth1` | interface to send from (Kali's soclab card) |
| `-t 10.10.10.20` | **target**: the victim whose table we poison (the defender) |
| `10.10.10.30` | the identity we **impersonate** (Metasploitable) |

Key distinction: `-t` = who we fool; trailing IP = who we pretend to be.

## Proving the attack: ip neigh and its signature
`ip neigh` (neigh = neighbours) shows the IP→MAC table.
Before → `10.10.10.30 ... 08:00:27:33:64:b7` (real).
During → `10.10.10.30 ... 08:00:27:77:e4:f8` (Kali's MAC).

**Poisoning signature: two different IPs pointing to the same MAC.** On a healthy network each MAC belongs to one device/IP; one MAC claiming several IPs means one machine is impersonating others.

### ARP table states (REACHABLE / STALE / FAILED)
Each entry tracks not just the mapping but how **fresh/trusted** it is:
| State | Meaning |
|-------|---------|
| REACHABLE | confirmed recently, trusted |
| STALE | we know the MAC, but haven't talked to it in a while — not re-confirmed |
| DELAY / PROBE | about to verify a STALE entry |
| FAILED | asked, nobody replied (seen when a host was off) |

> **Example:** STALE is like a friend's phone number you haven't used in a year — still in your book, but you're not sure it still works; you'd verify before relying on it.

**Why Kali's own line went STALE during the attack:** `.30` stayed REACHABLE because Kali floods replies for it constantly; Kali's real identity `.10` went idle (all activity now happens under the fake `.30`), so it cooled to STALE. Not a fault — a side effect of Kali hiding behind another identity.

## Indicator vs confirmed attack (my point)
One MAC on several IPs is a **strong indicator**, not 100% proof — rare legitimate cases exist (a router/host with several IPs). A good analyst treats it as "worth investigating", then confirms with corroborating evidence (a flood of unsolicited ARP replies, a flip-flop) before declaring an attack. This is the difference between a **false positive** and a **true positive**, and why analysts don't jump to conclusions from a single indicator.

## Detection 1: Suricata — a useful failure
`fast.log` showed nothing during the attack. **ARP is Layer 2 (Link) and carries no IP**; Suricata was watching IP traffic, so ARP passed under its radar.

Enabling `eve-log: - arp: enabled: yes` made Suricata **log** ARP events (we saw ~57, and one full event showed the lie clearly). But writing a rule failed:
```
protocol "arp" cannot be used in a signature
```
**Suricata 8 logs ARP but doesn't support ARP detection rules in practice.** A real tool limit, found by testing.

## Detection 2: arpwatch — the right tool
**Why arpwatch succeeds where Suricata fails:** arpwatch keeps a **reference IP→MAC table and remembers it**; it alerts when a binding changes. Suricata's rules are **stateless** — they inspect each packet alone, with no memory of what .30's MAC was a moment ago. Detecting ARP spoofing **requires memory of the previous state**, so the specialist tool is the right one.

> **Example:** arpwatch is a guard who knows residents' faces; a new face claiming to be the tenant of flat 30 rings the alarm. Suricata checks each visitor but remembers no faces.

Running it (silently, in the background, on soclab):
```bash
sudo nohup arpwatch -i enp0s8 -f /var/lib/arpwatch/arp.dat -N > /dev/null 2>&1 &
```
| Part | Meaning |
|------|---------|
| `-i enp0s8` | watch the soclab card |
| `-f .../arp.dat` | its reference table (its IP→MAC memory) |
| `-N` | no email reports (avoids the sendmail errors) |
| `nohup ... &` | run in background, survive terminal close |
| `> /dev/null 2>&1` | discard its screen output (it writes to syslog anyway) |

**Order matters:** teach the clean state first, then attack — otherwise it learns the poisoned state as normal. Its three alert types (all ARP-spoofing fingerprints):
- `changed ethernet address` — the MAC bound to an IP changed
- `ethernet mismatch` — a packet contradicts the recorded binding
- `flip flop` — the binding bounces between two MACs

It notices the change when ARP traffic carrying the new binding passes; a `ping` from the defender can force the update and trigger it.

`lladdr` (seen in `ip neigh` and `ip neigh replace`) = **link-layer address** = the MAC, in `ip` command terminology (generic because `ip` supports many network types).

## Defence: static ARP, and its limits
Lock the real binding so no reply can change it:
```bash
sudo ip neigh replace 10.10.10.30 lladdr 08:00:27:33:64:b7 dev enp0s8 nud permanent
```
`nud` (Neighbour Unreachability Detection) sets the entry's state; `permanent` = never expires, **ignores all ARP updates**. A normal entry auto-updates on any ARP reply (the vulnerability); a permanent one refuses them. `ip neigh show` then reads `PERMANENT`.

> **Example:** instead of believing anyone who says "I'm the tenant of flat 30", the guard has a locked, verified record and rejects any claim to change it.

**The limit I discovered:** I locked only the **defender's** table. During the attack a `ping .30` still failed, because Kali was poisoning the **other direction** and intercepting the return path. Stopping the attack restored the ping — proving the defence held and the failure was the ongoing interception. **One-sided static ARP protects that host's table but not a two-way conversation.**

Proper defence:
- **static ARP:** works, but doesn't scale (500 hosts × manual entries, updated on every change) → only for critical hosts; also in-memory, lost on reboot unless made persistent.
- **Dynamic ARP Inspection (DAI):** the enterprise answer, enforced on managed switches.

## Possible interview questions
- Why does ARP make spoofing possible? No authentication, and it accepts unsolicited (gratuitous) replies; the host updates its table on any reply.
- What's the signature of ARP poisoning? One MAC bound to several IPs (indicator, confirm with a reply flood / flip-flop).
- What does ip_forward do in a MITM? Makes the attacker relay intercepted packets to their real destination — the difference between spying (MITM) and cutting (DoS).
- Why does the attacker keep its own ARP table clean? So it alone knows the real map and can forward traffic, staying hidden.
- Why can't Suricata detect ARP spoofing here? ARP is Layer 2 with no IP; Suricata 8 logs ARP but has no ARP detection rules. And rules are stateless — detection needs memory of the previous binding.
- Why does arpwatch work? It keeps and remembers a reference IP→MAC table and alerts on changes.
- How do you defend against ARP spoofing? Static ARP entries on critical hosts (don't scale), or Dynamic ARP Inspection on managed switches.
- Indicator vs confirmed attack? An indicator warrants investigation; confirmation comes from corroborating evidence — the false-positive vs true-positive distinction.
- MITRE mapping? T1557.002 — Adversary-in-the-Middle: ARP Cache Poisoning.