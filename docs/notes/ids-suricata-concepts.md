# IDS & Suricata — Learning Notes

Concepts from Phase 3, in my own words, with examples. For what was actually done, see [Phase 3 — Suricata IDS](../phase-3-suricata.md).

## Why logs aren't enough: network layers
Data crossing a network is wrapped in layers, like a gift: a box, inside wrapping paper, inside an addressed envelope. The postman only reads the envelope; the receiver unwraps down to the content. Formally this is the **TCP/IP model**:

| Layer | Carries | Example |
|-------|---------|---------|
| Application | data programs understand | SSH password, web page |
| Transport | TCP/UDP, ports, SYN/ACK | the handshake |
| Network | addressing between networks | source/dest IP |
| Link | physical delivery on the LAN | MAC, ARP |

`auth.log` is written by **sshd**, an application at the **top** layer. sshd only sees a connection once the lower layers are unwrapped and real content (a login attempt) reaches it. A **port scan stops at the Transport layer** — a bare SYN carries no application data — so it never reaches sshd, and `auth.log` stays silent. An **IDS captures packets at the bottom, before they're unwrapped**, so it sees every layer, including the scan.

## IDS and Suricata
An **IDS (Intrusion Detection System)** sits on the network, inspects every packet, compares it against patterns, and raises an **alert** on a match. It **detects and warns only** — like a CCTV camera that records a thief but doesn't stop him. The tool that actually **blocks** is an **IPS**, and it's the same Suricata with the action `drop` instead of `alert` (a later phase).

**Suricata** is a popular free/open-source IDS. The guard-vs-camera picture: `auth.log` is the guard at the door (sees only who approaches the door); Suricata is a camera over the whole street (sees the thief checking every window).

## Configuring Suricata: the three questions
For Suricata to work usefully it needs three answers, all in `/etc/suricata/suricata.yaml`:

**1. Which card to watch?** — `af-packet: interface: enp0s8`. The defender has two cards; we watch `enp0s8` (soclab, where attacks come from), not `enp0s3` (NAT). Like placing a camera at the entrance the danger uses.

**2. What is "my network"?** — `HOME_NET: [10.10.10.0/24]`. This defines the boundary between "me" and "outside" (`EXTERNAL_NET` = everything else). It isn't about ignoring the inside — it's a **label for direction**, so rules can say "alert if something comes *from outside* *toward my network*". The guard must know residents from strangers.

**3. What patterns to watch for?** — **rules**. Suricata has eyes but needs a list of what's suspicious. Two kinds: downloaded sets (ET Open, ~53k rules, via `suricata-update`) and our own custom rules.

## The TCP 3-way handshake
Every normal TCP connection opens with three steps, like knocking and a short exchange before entering:
```
client → SYN      "I want to open a connection"
server → SYN-ACK  "OK, go ahead"
client → ACK      "done, let's start"   → connection open
```
These little markers (SYN, ACK, RST, FIN) are **TCP flags**.

## Why a SYN scan is invisible to auth.log
Nmap's default scan **deliberately doesn't finish** the handshake:
```
nmap → SYN       "is port 445 open?"
srv  → SYN-ACK   "yes"
nmap → RST       "never mind, drop it"   → connection never completes
```
It does this for **speed** (no need to complete thousands of connections) and **stealth** (the connection never completes, so sshd is never invoked → nothing in auth.log — the layers lesson again). The scan's **fingerprint**: many SYN packets, from one source, to many ports, in a short time.

## Anatomy of a detection rule
Our final working rule:
```
alert tcp any any -> $HOME_NET any (msg:"LOCAL Nmap TCP scan detected"; flow:to_server; flags:S+; threshold:type both, track by_src, count 15, seconds 10; sid:1000001; rev:3;)
```

**Header** (before the parenthesis) — *who, from/to where*:
```
alert   tcp   any   any   ->   $HOME_NET   any
action  proto srcIP srcPort dir  destIP    destPort
```
| Part | Meaning |
|------|---------|
| `alert` | action: raise an alert on match (the other action is `drop` → IPS) |
| `tcp` | protocol (others: `udp`, `icmp` for ping, `ip`, and app protocols like `http`, `dns`) |
| source `any any` | any source IP, any source port — the attacker's source port is a random ephemeral port (>1024), so there's nothing fixed to match |
| `->` | direction |
| dest `$HOME_NET any` | toward my network, any port — a scan hits many ports, so we don't fix one |

Why source `any` and not `$EXTERNAL_NET`: in this lab the attacker shares the subnet (inside HOME_NET), so it isn't "external" and `$EXTERNAL_NET` never matched.

**Options** (inside the parenthesis) — *the exact fingerprint*:
| Option | Meaning |
|--------|---------|
| `msg:"..."` | text shown in the log on a match; I write it to know which rule fired |
| `flow:to_server` | match only packets going *toward* the target (the attacker's SYNs), not the replies — the reply carries SYN-ACK, a different flag set |
| `flags:S+` | match packets with the SYN flag. `S` = "SYN and nothing else" (too strict, failed here); `S+` = "SYN present, other flags allowed" (what worked) |
| `threshold:...` | turns a burst into one meaningful alert (below) |
| `sid:1000001` | Signature ID — a unique number I choose; 1000000+ is reserved for local rules so it never clashes with ET Open |
| `rev:3` | revision — I bump it each time I edit the rule (we reached 3) |

## The threshold: signal, not noise
Every connection starts with a SYN, including my own SSH. Alerting on every SYN is useless noise (the noisy test rule proved it — dozens of lines). The threshold tells apart one innocent SYN from a burst:
```
threshold: type both, track by_src, count 15, seconds 10
```
| Part | Meaning |
|------|---------|
| `track by_src` | count per source IP (per attacker) |
| `count 15` | don't alert until 15 packets |
| `seconds 10` | within 10 seconds |
| `type both` | alert only on reaching the count, and only **once**, not per packet |

Result: instead of hundreds of raw lines, **one clean alert per scan**. The numbers 15/10 are a **choice**, tuning sensitivity: too low (e.g. 5) fires on normal traffic (false positives); too high misses slow scans. Balancing this is the heart of a SOC analyst's job — a rule's quality is in telling malicious from normal, not in how much it fires.

## Suricata's log files
All in `/var/log/suricata/`:
| File | Contains | Use |
|------|----------|-----|
| `fast.log` | **alerts only**, one line each, plain text | quick "did something fire?" |
| `eve.json` | **every** event (alerts, flows, DNS, stats), JSON | deep investigation |
| `suricata.log` | Suricata's own log (did it start? how many rules? errors?) | diagnosing Suricata itself |
| `stats.log` | periodic counters | performance |

Key difference: a normal connection (`flow`) appears in `eve.json` but **not** in `fast.log`; an `alert` appears in both. So to see every port a scan touched, read `eve.json`, not `fast.log`. Picture: `fast.log` is the station's **alarm log** (only rings on an alarm); `eve.json` is the **CCTV** (records everything). An alert in a threshold rule shows the port/time of the packet that *hit the count*, not the whole attack — the full picture is in `eve.json`.

## Rule file location
Rule files must sit where `default-rule-path` points: `/var/lib/suricata/rules/`, not `/etc/suricata/rules/`. `.rules` is just the extension (like `.txt`); `local` is a convention for "my own rules", vs `suricata.rules` (ET Open). Opening a non-existent path in `nano` creates the file on save; `mv` moves (or renames) a file.

## Commands and flags used
| Command | What it does |
|---------|--------------|
| `cp file file.bak` | copy → make a backup before editing |
| `mv a b` | move or rename a file |
| `ls -l <file>` | show a file's details (permissions, size, date) — used to find where it really is |
| `suricata -V` | version |
| `suricata -T -c <cfg> -v` | test config + rules without running (`-T` test, `-c` config, `-v` verbose) |
| `systemctl enable --now suricata` | start now + on boot |
| `systemctl status/restart suricata` | check / restart the service |
| `tail <file>` | last 10 lines |
| `tail -f <file>` | **follow**: stay open, show new lines live (Ctrl+C to stop) |
| `grep "x" file` | lines containing x |
| `grep -o 'pat' file` | print **only** the matched part, not the whole line |
| `sort` | sort lines (so identical ones become adjacent) |
| `uniq -c` | merge adjacent identical lines, prefix each with its **count** |
| `tail -1` | last single line (the number sets how many from the end) |
| `a | b` | pipe: feed a's output into b |

## The log-analysis one-liner
```bash
grep -o '"event_type":"[^"]*"' eve.json | sort | uniq -c
```
Reads as: extract each event type, sort, count each. Example on a fruits file (`apple, banana, apple, cherry, banana, apple`):
```
sort fruits | uniq -c  →   3 apple / 2 banana / 1 cherry
```
`sort` first is required because `uniq` only merges **adjacent** duplicates. `grep -o` prints just the match, not the whole line. On eve.json it gives, at a glance, how many of each event type exist — that's how we saw hundreds of `flow` but zero `alert` before fixing the rule. The pattern **extract-a-field → count** (`grep -o … | sort | uniq -c`) is a core log-analysis trick.

### Why `[^"]*` and not just `.*`
In `"event_type":".*"`, `.*` is **greedy** — it grabs as much as possible, running to the **last** quote on the line and swallowing half the JSON. `[^"]` means "any character except a quote", so `[^"]*` stops at the **first** closing quote — capturing exactly `flow`. Greedy `.*` overshoots; `[^"]*` respects the boundary.

## Possible interview questions
- Why doesn't a port scan appear in `auth.log`? It stops at the Transport layer and never reaches sshd (Application layer), so no login event is logged.
- IDS vs IPS? IDS detects and alerts (`alert`); IPS also blocks (`drop`) — same Suricata, different action.
- What is HOME_NET? The network Suricata protects; with EXTERNAL_NET it labels direction for rules.
- `flags:S` vs `flags:S+`? "SYN only" vs "SYN plus any other flags"; `S+` is safer for scan detection.
- Why did `$EXTERNAL_NET` fail here? The attacker shares the subnet (inside HOME_NET), so it isn't external.
- Why a threshold? To turn a burst of SYNs into one meaningful alert and ignore single normal connections.
- `fast.log` vs `eve.json`? Alerts only vs every event; investigate in eve.json.
- What does `suricata -T` do? Validates config and rules without running — catches errors before start.