# Port Scan & Detection — Learning Notes

Concepts I learned in Phase 2, written in my own words, with examples.
For what was actually done, see [Phase 2 — Port Scan & Log Detection](../phase-2-portscan.md).

## ss (socket statistics)
Shows all **sockets** on the machine — every open port and every active connection. A socket = one endpoint of a connection (IP + port + protocol). It's the modern replacement for the older `netstat`.

It works by reading a table the Linux kernel keeps of all connections, so it's fast.

```bash
ss -tlnp
```
| Flag | Meaning |
|------|---------|
| `-t` | TCP only |
| `-l` | listening ports (open doors) |
| `-n` | numbers, not names |
| `-p` | which program owns each port (needs sudo) |

Other useful forms:
```bash
ss -tan      # all TCP connections (listening + established)
ss -s        # quick summary
ss -tan | grep ":22"   # only what concerns port 22
```

## ARP (Address Resolution Protocol)
Translates an **IP address** into a **MAC address**.

Two kinds of address, in two layers:
- **IP** (`10.10.10.20`): logical, changeable, used to route across networks.
- **MAC** (`08:00:27:...`): physical, burned into the network card, doesn't change.

Inside one local network, machines actually talk by **MAC**, not IP. So before sending to an IP, a machine must find the matching MAC — that's ARP:
```
1. Kali broadcasts to the whole network: "who has 10.10.10.20?"
2. Only the owner replies: the defender says "me, my MAC is 08:00:27:..."
3. Kali caches the IP→MAC mapping in its ARP table
4. Now Kali can actually send
```
```bash
ip neigh    # the ARP table (neigh = neighbours); FAILED = no reply
```

**Security note:** ARP is naive — it trusts any reply with no verification. A fake reply ("I own 10.10.10.20") redirects traffic to the attacker. That's **ARP spoofing** (Phase 4).

> **Example:** ARP is like shouting in a crowded room "who is Ahmed?". Ahmed raises his hand. But nothing stops an impostor from raising his hand too, so you hand your message to the wrong person — that's ARP spoofing.

## Logs and auth.log
On Linux, systems and programs constantly write what happens to them into text files called **logs**, one line per event with a timestamp — a diary for the system. Most live in `/var/log/`:
```bash
ls /var/log/    # syslog (everything), auth.log (auth), kern.log (kernel), ...
```

**`/var/log/auth.log`** is the log specialised in **authentication & authorization** — who tried to prove their identity, who tried to raise their privileges. It records:
- SSH login attempts (successful and failed)
- every `sudo` use, with the full command
- logins/logouts, user creation, password changes

(On Red Hat-family systems it's `/var/log/secure` instead.)

Reading it (needs sudo — it's sensitive):
```bash
sudo cat  /var/log/auth.log            # whole file
sudo tail /var/log/auth.log            # last 10 lines
sudo tail -f /var/log/auth.log         # live: new lines appear as they happen
sudo grep "10.10.10.10" /var/log/auth.log
```
`tail -f` is great for learning: leave it running, log in from another window, watch the log being written live.

It's the first place a SOC analyst looks during an intrusion: who tried to log in, from where, how many times, when did they succeed.

> **Example:** auth.log is like the guard's logbook at a building's door: "3am, someone tried to enter and failed", "4am, the real resident came in". But the guard only records people who approached the **door**. A thief circling the building checking windows from outside (a port scan) never appears — he never came near the door.

## grep (search in text)
Give it a word and a file; it prints only the lines containing that word — like Ctrl+F for the terminal, but far stronger.
```
grep [options] "word" file
```
| Option | Meaning |
|--------|---------|
| `-i` | ignore case (Failed = failed) |
| `-r` | search recursively in a folder |
| `-n` | show line numbers |
| `-v` | invert: lines that do **not** match |
| `-c` | count matching lines only |

Its real power is the **pipe** (`|`) — search the output of another command:
```bash
ss -tan | grep ":22"     # from all connections, only port 22
ip a | grep "inet"       # from all network info, only address lines
```
grep is one of the most-used SOC tools: logs are huge, and you're always looking for a needle (an IP, the word `Failed`, a user).

## Network layers: why auth.log and an IDS see different things
Data crossing a network passes through **layers**, like a postal letter:

| Layer | Letter | Network |
|-------|--------|---------|
| Content | the text inside the envelope | application data: password, command, web page |
| Envelope | sender/recipient on the outside | the packet: source IP, dest IP, ports |

- **Network layer** = the envelope: from where, to where.
- **Application layer** = the content: what's in the message.

**auth.log works at the application layer.** It's written by **sshd**, an application. sshd only sees a message *after* the envelopes are opened and the content reaches it — and it only logs its own events: a **login attempt**. If nothing reaches sshd, there's nothing to log.

**A port scan stays at the network layer.** Kali never tries to log in; it just sends a tiny envelope to each port and waits to see who replies. The content is never opened, sshd is never called, so the application sees nothing → auth.log stays silent.

> **Example:** the postman touches your mailbox to see if it's open, then walks on. Inside the house you heard nothing — he never knocked or delivered. auth.log is "you inside the house": it only records who knocked on the door.

**An IDS (Intrusion Detection System)** doesn't sit inside one application. It sits on the **network itself** and inspects **every packet**, regardless of where it's headed. So it sees Kali sending envelopes to port 22, then 23, then 80... hundreds in seconds. That pattern — **one source hitting many ports fast** — is the scan's fingerprint, and the IDS raises an **alert**.

> **Example:** an IDS is a CCTV camera over the whole street, not just one door. The door guard (auth.log) sees only who approached his door. The street camera (IDS) sees the thief checking every house, even if he never touches a door.

Summary:
| | auth.log | IDS (Suricata) |
|---|---|---|
| Works in | the application (sshd) | the network |
| Layer | application | network |
| Sees | login attempts only | every packet |
| Detects a port scan? | ❌ no | ✅ yes |
| Detects SSH brute force? | ✅ yes | ✅ yes |

They **complement** each other: auth.log is deep but narrow (one application in detail); an IDS is wide (the whole network). A real SOC uses both.

## Possible interview questions
- **What is `ss`?** A tool that lists sockets (open ports and active connections) by reading the kernel's table; the modern `netstat`.
- **What is ARP for?** To find the MAC address behind an IP on the local network, because machines talk by MAC there. It's naive (trusts any reply) → ARP spoofing.
- **What is `auth.log`?** The Linux log for authentication and privilege events (SSH logins, sudo, user changes), in `/var/log/auth.log`.
- **What does `grep -i` do?** Searches text for a pattern, ignoring upper/lowercase.
- **What is an IDS?** A system that inspects network traffic to detect malicious patterns (like a port scan) and raise alerts.
- **Why does a port scan escape auth.log but an IDS catches it?** The scan stays at the network layer and never reaches the application (no login attempt), so auth.log (written by sshd) sees nothing. An IDS watches the network layer directly, so it sees the packets.