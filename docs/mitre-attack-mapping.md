# MITRE ATT&CK Mapping — SOC Home Lab

A single map of every technique touched in this lab, phase by phase, with the evidence that backs each entry. See each phase's own doc for the full narrative.

**How to read the "Tagged by" column:**
- **Wazuh (native)** — the rule itself carries the MITRE tag, visible in its metadata (`<mitre><id>...</id></mitre>`) and in the dashboard.
- **My mapping** — Wazuh's rule does not tag this technique; I assigned it myself based on what the attack actually did. Still accurate, but it is my judgment, not the tool's.

## Summary table

| Technique ID | Technique Name | Tactic | Phase | Evidence | Tagged by |
|---|---|---|---|---|---|
| T1046 | Network Service Discovery | Discovery | 2, 3, 5, 6, 7 | nmap / `/dev/tcp` scans; Suricata rule 86601 (sid 1000001) | My mapping |
| T1557.002 | Adversary-in-the-Middle: ARP Cache Poisoning | Collection, Credential Access | 4 | `arpspoof` both directions; `ip neigh` shows one MAC on two IPs; arpwatch alerts | My mapping (stated explicitly in phase 4) |
| T1110 | Brute Force (general) | Credential Access | 6, 7 | Wazuh rule 5712 metadata (phase 6, never fired yet); rule 5712 fired for real in phase 7 (Hydra, fast run); evaded in phase 7 (Hydra, slow run, no rule fired) | Wazuh (native) |
| T1110.001 | Password Guessing | Credential Access | 7 | Hydra wordlist attack on a real account (`a5rasx`); rules 5760/5763 | My mapping, on top of Wazuh's general T1110 tag |
| T1078 | Valid Accounts | Initial Access, Persistence | 6 | Successful SSH login as the final link in `correlate.py`'s `BREACH STORY` (rule 5715) | My mapping |
| T1548.003 | Sudo and Sudo Caching | Privilege Escalation, Defense Evasion | 6 | Wazuh rule 5402, fired on my own `sudo` commands during investigation — not an attack, but a reminder that the SIEM logs the administrator too | Wazuh (native) |

## Per-phase detail

### Phase 2 & 3 — Port scan (T1046)
`nmap` against `soc-defender` is textbook Network Service Discovery: the attacker enumerates which services are reachable before doing anything else. Phase 2 showed it leaves **no trace** in `auth.log` (it never touches authentication); Phase 3 is the reason an IDS exists at all — Suricata's own rule (sid 1000001) is what actually catches it, since nothing in MITRE's own tooling flags this for you automatically here.

### Phase 4 — ARP spoofing (T1557.002)
The only technique in the lab explicitly named with its MITRE ID in its own phase doc. Both ARP tables were poisoned to run a Man-in-the-Middle; `arpwatch`'s `changed ethernet address` / `flip flop` alerts are the detection evidence. Also the only phase where an evasion attempt was tested end to end (slow poisoning, still caught — a state-based detector doesn't care about speed) and one was only reasoned through, not run (MAC spoofing, documented honestly as a concept, not a test).

### Phase 5 — Scan under IPS (still T1046)
Same technique as phases 2–3, same scan — the difference is the *outcome*, not the technique: Suricata in IPS mode silently drops the matching packets, and the attacker's own nmap output (stuck at 43%, 4+ minutes) is itself part of the evidence.

### Phase 6 — Correlation and its two "new" techniques
This is the only phase where a **chain** of techniques is linked into one story rather than looked at one at a time: scan (T1046) → brute-force attempts (T1110, Wazuh's own tag, though the rule had not actually fired yet at this point) → successful login (T1078, my own mapping — Wazuh does not tag a plain login success with an ATT&CK ID). Rule 5402 (T1548.003) is unrelated to any simulated attack; it fired on my own `sudo` usage while investigating, which is worth keeping in the map as a note on SIEM visibility, not as an attack technique.

### Phase 7 — Brute force, for real (T1110 / T1110.001)
The first phase where T1110 is backed by an actual firing of Wazuh's native rule, not just its metadata. Hydra's fast run (4 parallel attempts) crossed rule 5712's threshold (8 failures / 120 s) in under 4 seconds. The slow run (one attempt every 20 s via `-c 20`) is the clearest evasion result in the whole lab: identical attack, identical target, **zero alerts**, because the same threshold that defines the detection also defines its blind spot. Guessing a real account's password specifically (rather than guessing usernames) is the sub-technique T1110.001, evidenced by rules 5760/5763.

## Wazuh rule reference

Every rule ID that actually appeared in `alerts.json` across the lab, in one place. Some of these (5710, 5758, 5760) are supporting evidence for a technique above but aren't themselves a separate technique; 5402 isn't part of any simulated attack at all.

| Rule ID | Level | Meaning | Phase(s) | MITRE link above |
|---|---|---|---|---|
| 86601 | 3 | Suricata alert wrapper for my own rule `sid 1000001` ("LOCAL Nmap TCP scan detected") | 3, 5, 6, 7 | T1046 |
| 5710 | 5 | SSH login attempt, username does not exist | 6, 7 | supports T1110 / T1110.001 (one failed attempt; not brute force by itself) |
| 5712 | 10 | SSH brute force, username guessing — 8+ failures of rule 5710 in 120 s, same source IP | 6 (metadata only), 7 (actually fired, and evaded) | T1110 |
| 5715 | 3 | SSH authentication success | 6, 7 | T1078 |
| 5758 | 8 | `sshd` itself: "Maximum authentication attempts exceeded" — the SSH daemon cutting off a connection, independent of any Wazuh threshold | 7 | supports T1110 / T1110.001, not a separate technique |
| 5760 | 5 | SSH login attempt, wrong password on a **real** account | 7 | supports T1110.001 |
| 5763 | 10 | SSH brute force, password guessing on a real account — same idea as 5712, for real usernames | 7 | T1110.001 |
| 5402 | 3 | Successful `sudo` to root | 6 | none — fired on my own admin commands, not a simulated attack |

Note on 5712 vs 5763: Wazuh splits brute force into two separate rules depending on *what* is being guessed — a username (5712, built on top of 5710) or a password on a real account (5763, built on top of 5760). Both share the same `frequency`/`timeframe` logic, so the evasion result from phase 7 (spacing attempts out defeats the threshold) applies equally to both, even though only 5712 was the one actually tested against the slow attack.

## What is deliberately *not* mapped

- **A plain scan with nothing following it** is only ever T1046 — it is not escalated to anything else unless phase 6's correlation chain actually links it to a later login.
- **False-positive testing** (phase 7, section 4) produced no attack at all by design, so nothing there is mapped to a technique; it exists to show the *absence* of a false alarm on ordinary user error, not a technique.
- **Reconnaissance that was reasoned through but not executed** (MAC spoofing, phase 4) is noted in that phase's doc as a concept, and is left out of this table — only techniques that were actually run belong here.

## Next

As phase 7's own doc notes, the fuller false-positive scenario (scan + failures + success, all benign) is still open, blocked by Suricata's per-source scan suppression. If that test is redesigned and run later, it would most likely map to the same T1046 → T1110 → T1078 chain shown above — the point of running it would be to confirm the *rules* can tell intent apart, not to find a new technique.
