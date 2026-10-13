# Phase 7 — Real brute force, evasion, and false positives

## Goal

Phase 6 proved the pipeline end to end, but the "brute force" in it was six manual SSH attempts — not a real attack, and never enough to trip Wazuh's own brute-force rule (it needs 8 failures in 120 s). This phase closes that gap: a real password-guessing tool, a test of whether the detection can be evaded by going slow, and a first honest measurement of false positives.

**Attacker:** `wazuh-server` again (not Kali), to keep the lab inside the host's 8 GB RAM limit. The tool matters here, not which VM runs it.

## 1. A real brute-force attack with Hydra

Installed Hydra 9.6 (`sudo apt install -y hydra`) and built two small wordlists:

```
userlist.txt: admin, root, test, fakeuser, guest, backup
passlist.txt: 123456, password, admin123, qwerty, letmein, toor, changeme, 111111
```

48 combinations (6 × 8) — enough to cross Wazuh's threshold, small enough not to stress a host that was already tight on memory.

```bash
hydra -L ~/userlist.txt -P ~/passlist.txt -t 4 ssh://10.10.10.20
```

`-t 4` runs 4 login attempts in parallel. Hydra stopped itself after a handful of tries (`all children were disabled due too many connection errors`) — `soc-defender`'s own `sshd` was throttling concurrent auth attempts, a defence that already existed before any Wazuh rule got involved. That did not matter: 8 failures is all the rule needs, and they arrived in under 4 seconds.

**Result — rule 5712 fired for the first time:**

```
2026-10-13T20:27:16 5710 5  sshd: Attempt to login using a non-existent user
...(8 of these in 4 seconds)...
2026-10-13T20:27:20 5712 10 sshd: brute force trying to get access to the system. Non existent user.
```

Level 10, far above the level-5 individual attempts. This is the first time this built-in rule has actually triggered in the lab.

## 2. Evasion: can the same rule be avoided by going slow?

Rule 5712 is `frequency="8" timeframe="120"`: 8 failures inside 120 seconds. If an attacker spaces attempts out, they never accumulate fast enough.

First attempt used `-w 20` (20 s), which turned out to be the wrong option — `-w` is the reply-wait timeout, not the delay between attempts. The failures still arrived every couple of seconds and rule 5712 fired again, unchanged from the fast run. The correct option, confirmed with `hydra -h`, is `-c TIME` ("wait time per login attempt over all threads, enforces -t 1"):

```bash
rm -f ~/hydra.restore     # clear a leftover restore file from the earlier, interrupted runs
hydra -L ~/userlist.txt -P ~/passlist.txt -c 20 ssh://10.10.10.20
```

**Result — no alert at all:**

```
20:36:53  20:36:53  20:36:53  20:36:55   (Hydra's own startup burst)
20:37:15  20:37:37  20:37:57             (steady ~20 s apart from here on)
```

7 failed logins spread over more than a minute, same user list, same target, same attacker — **rule 5712 never fired.** At one attempt every 20 seconds it takes about 140 s to reach 8 failures, past the rule's 120 s window.

**Conclusion:** rule 5712, like the arpwatch state-based detection in phase 4, is a threshold detector, and thresholds built on *frequency + time* can be defeated simply by being patient, with no technical trick needed. This is a recurring pattern in the lab, not a one-off weakness.

## 3. A second brute-force rule discovered along the way

The attempts above used a non-existent user. Testing a wrong *password* for a real account (`a5rasx`) surfaced rules I hadn't seen before:

| Rule | Level | Meaning |
|---|---|---|
| 5760 | 5 | `authentication failed` — wrong password, real user |
| 5758 | 8 | `Maximum authentication attempts exceeded` (sshd itself cutting off a connection) |
| 5763 | 10 | `brute force ... Authentication failed` — same idea as 5712, for real-user password guessing |

So Wazuh ships two separate brute-force rules depending on whether the attacker is guessing *usernames* (5712) or *passwords on a real account* (5763). Both appeared during the fast Hydra run, since the wordlist happened to include a real-looking name.

## 4. False positives: does ordinary human error trigger an alert?

Original plan: scan, then 3 failed logins, then a real success, all from the same IP, with no attacker intent — and check whether the correlation script (`correlate.py` from phase 6) wrongly calls it a `BREACH STORY`.

Two limits got in the way, both worth documenting honestly:

- **Suricata's scan rule (sid 1000001) is rate-limited per source.** After the first scan alert fired, a second scan from the same IP (`10.10.10.40`) produced no new Suricata alert at all — confirmed by checking `alerts.json` for rule `86601` and finding only the original timestamp. A benign "second scan" could not be generated to test against.
- **`correlate.py` as written only reports the first story it finds per IP, then stops (`break`).** Removing the `break` was necessary before any second scenario on the same IP could be evaluated at all — otherwise the script silently ignores anything that happens after the first match. Fixed version saved as `correlate-v5-no-break.py`.

With a real "second scan" ruled out, the test was simplified to what the lab could actually produce: **3 wrong passwords on a real account, then a correct login, no scan at all** — the closest thing to an everyday mistake (typing a password wrong a few times, then getting it right):

```bash
hydra -l a5rasx -p "oops1" ssh://10.10.10.20
hydra -l a5rasx -p "oops2" ssh://10.10.10.20
hydra -l a5rasx -p "oops3" ssh://10.10.10.20
ssh a5rasx@10.10.10.20 "echo real-login-ok"
```

**Result:**

```
20:52:21 5760 5  authentication failed
20:52:23 5760 5  authentication failed
20:52:27 5760 5  authentication failed
20:52:39 5715 3  authentication success
```

Neither 5712 nor 5763 fired — 3 failures is under their 8-attempt threshold. **No false alarm on an ordinary mistake.** This is a real, if narrow, result: the threshold that lets a patient attacker evade detection (section 2) is the same threshold that protects a normal user from a false alarm. It was not possible, with this lab's current rules, to test the fuller scan+fail+success false-positive scenario from the original plan; that remains open for later.

## Problems & Fixes

**1. `-w` is not a delay between attempts.** It sets the reply-wait timeout; the real option for spacing out logins is `-c` (also forces `-t 1`). Caught by checking `hydra -h` instead of assuming.

**2. A stale `hydra.restore` file skewed timing on a retry.** Hydra saves a restore file after an interrupted run and warns before overwriting it; an old one contaminated the next timed test. Fixed with `rm -f ~/hydra.restore` before any run whose exact timing matters.

**3. Measuring "since when" by reading a Python one-liner's own `sudo` prompt timestamp was unreliable at first** (one test picked up an unrelated old scan from a previous session). Fixed by printing `date -u` immediately before each attack and filtering `alerts.json` on `timestamp >= START` from that exact moment.

**4. `sshpass` with default settings answered only the first password prompt and then hung**, because OpenSSH asked a second time; no alert resulted and the shell appeared to do nothing. Switching to Hydra's own `-l`/`-p` single-target mode gave a clean, single, verifiable failure instead.

**5. Suricata's scan rule would not re-fire for a second scan from the same source** while its internal threshold/suppression window was still active — discovered when a planned "second benign scan" produced zero new alerts in `alerts.json`. This blocked the original false-positive design and is now a documented limitation (section 4), not a bug in Wazuh or in this lab's rule.

**6. `correlate.py` only reported the first matching story per IP (an early `break`), silently hiding any later story — attack or benign — for that same address.** Found while investigating why a brand-new benign test produced yesterday's old breach story instead of nothing. Fixed by looping over every scan for an IP and reporting each qualifying story, not just the first.

## MITRE ATT&CK

| Technique | Where | Evidence |
|---|---|---|
| T1110.001 Password Guessing | Hydra fast run | rule 5712/5763 triggered |
| T1110 Brute Force (general) | both Hydra runs | rule 5712 (fast), no rule (slow) |

## Evidence

- `evidence/phase-7/commands-used.txt`
- `evidence/phase-7/fast-attack-triggers-5712.txt`
- `evidence/phase-7/slow-attack-evades-5712.txt`
- `evidence/phase-7/benign-3fails-then-success.txt`
- `evidence/phase-7/correlate-v5-no-break.py`

## Next

A full scan+fail+success false-positive test (blocked here by Suricata's per-source scan suppression) remains open for later. Then: a full MITRE ATT&CK map across every phase, and an updated README.
