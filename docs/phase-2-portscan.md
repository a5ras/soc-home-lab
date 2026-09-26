# Phase 2 — Port Scan & Log Detection

## Goal
Run the first real attack (a port scan from Kali), then switch to the defender and ask the core SOC question: **did it leave a trace?**

## Step 1 — The truth from inside (defender)
What ports is the defender actually exposing? Seen from the machine itself:
```bash
sudo ss -tlnp
```
| Flag | Meaning |
|------|---------|
| `-t` | TCP only |
| `-l` | listening ports (open doors) |
| `-n` | numbers, not names |
| `-p` | which program owns each port (needs sudo) |

Result:
| Port | Local Address   | Program          | Reachable from             |
|------|-----------------|------------------|----------------------------|
| 22   | `0.0.0.0:22`    | sshd             | any network (NAT + soclab) |
| 53   | `127.0.0.53:53` | systemd-resolved | the machine itself only    |

**Key idea — `0.0.0.0` vs `127.0.0.x`:**
- `0.0.0.0` = listen on **all interfaces** → exposed to the network.
- `127.0.0.x` (loopback) = listen for **the machine itself only** → invisible to the network.

So from outside, only port 22 should be visible. Binding a service to `127.0.0.1` is a basic hardening technique: it disappears from the network.

> **What is a port?** The IP is the address of a building; the port is the flat number inside it. A message needs both to reach the right program. SSH lives in flat 22, DNS in flat 53.

## Step 2 — The attacker's view from outside (Kali)
```bash
nmap 10.10.10.20
```
```
PORT     STATE  SERVICE
22/tcp   open   ssh
Not shown: 999 closed tcp ports (reset)
MAC Address: 08:00:27:... (Oracle VirtualBox virtual NIC)
```
- Only **22/tcp open** — exactly matching `ss`. Port 53 never appeared, because it only listens on loopback. **Confirmed by experiment.**
- `Host is up`: nmap first sent an **ARP** request ("who has 10.10.10.20?"); the defender replied.
- The **MAC address** is visible only because attacker and target are on the same local network.

**Port states in nmap:**
| State    | Meaning                                                        |
|----------|----------------------------------------------------------------|
| open     | a program is listening behind the port                         |
| closed   | host is there, but nothing behind the port (replies with a TCP **RST**) |
| filtered | no reply at all — usually a **firewall**                       |

## Step 3 — The SOC question: did the scan leave a trace?
Search the auth log for Kali's address:
```bash
sudo grep -i "10.10.10.10" /var/log/auth.log
```
**After the scan: nothing.** `auth.log` records **authentication** events (login attempts). A plain port scan never tries to log in — it just knocks on doors and leaves — so it doesn't appear.

> **Analogy — the thief trying door handles.** A thief walks down the street testing every door handle to see which is open. He never entered any house, so the "entry log" is empty — but he now knows which doors are unlocked. That's a port scan: no login, no trace in auth.log, but the attacker has mapped the target.

## Step 4 — Compare with a real login attempt
```bash
# From Kali
ssh wronguser@10.10.10.20     # wrong user, let it fail
```
```bash
# On the defender
sudo grep -i "10.10.10.10" /var/log/auth.log
```
This time, **three new lines appear:**
```
Invalid user wronguser from 10.10.10.10 port 52038
pam_unix(sshd:auth): authentication failure ... rhost=10.10.10.10
Failed password for invalid user wronguser from 10.10.10.10
```
| Line | Meaning |
|------|---------|
| `Invalid user wronguser` | a login came in for a user that doesn't exist |
| `pam_unix(sshd:auth): authentication failure ... rhost=10.10.10.10` | PAM (the auth system) rejected it; `rhost` = source address |
| `Failed password for invalid user` | the password check failed |

Comparison:
| Event                          | Trace in auth.log? |
|--------------------------------|--------------------|
| Port scan (knocking)           | ❌ nothing         |
| Failed login (trying to enter) | ✅ three clear lines |

## Step 5 — sudo is logged too
The same search also showed lines like:
```
sudo: a5rasx : TTY=/dev/pts/0 ; PWD=/home/a5rasx ; USER=root ; COMMAND=/usr/bin/grep ...
```
That's me. **Every `sudo` command is logged**, with the full command and who ran it.

Double-edged:
- **For the defender (SOC):** great — if an attacker takes over an account and uses `sudo`, every command they run is recorded.
- **For the attacker:** if they can read this log, it may reveal useful information, sometimes even a password typed by mistake on the command line.

> **Analogy — the vault camera.** The sudo log is like a CCTV camera at the company vault: everyone who opens it is recorded — who, when, what they took. Useful for the owner, dangerous if the footage falls into the thief's hands.

## Key takeaway
A port scan stays at the **network layer** and never touches authentication, so log-based tools like `auth.log` are **blind** to it. To detect a scan I need to watch the **network itself** (every packet), which is exactly what an **IDS** does.

→ This is the reason for **Phase 3: Suricata (IDS)**.

## Detection idea (for later)
A port scan = one source IP hitting **many different ports** in a very short time. That pattern is what an IDS rule will look for.

## Possible interview questions
- **What is a port?** A number that identifies a specific service on a machine, so one IP can run many services at once (IP = building, port = flat number).
- **What does `0.0.0.0` mean?** "All IPv4 interfaces" when listening → the service is reachable from every network, which enlarges the attack surface. It's a placeholder for "any", not a real host address. (In routing, `0.0.0.0/0` means "all destinations".)
- **What's the difference between `closed` and `filtered` in nmap?** `closed` = the host actively replies with a TCP RST (nothing listening). `filtered` = no reply at all, usually a firewall dropping the packet.
- **Why doesn't a port scan show up in `auth.log`?** Because a scan never reaches the authentication layer — it only checks which ports are open, without trying to log in. `auth.log` only records authentication events.
- **Which attacks appear in `auth.log`, which don't?** Appear: anything touching authentication (failed logins, SSH brute force, sudo use). Don't: network-level activity like port scans → need an IDS.
- **How would you detect a port scan then?** Watch the network with an IDS (e.g. Suricata): one source IP hitting many ports in a short window.
- **How does nmap know a host is up on a local network?** It sends an ARP request; a reply means the host is alive. (This is why the scan failed earlier when the defender was powered off.)

## Screenshots
- [ ] `ss -tlnp` on the defender (ports from inside)
- [ ] `nmap 10.10.10.20` from Kali (ports from outside)
- [ ] `grep` after the scan (empty — scan left no trace)
- [ ] `grep` after the failed login (three new lines)