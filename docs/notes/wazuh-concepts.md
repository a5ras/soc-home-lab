# Wazuh and correlation — concept notes

> Written in my own words, with everyday examples so I can explain it out loud. Companion to `docs/phase-6-wazuh.md`.

## 1. The big picture (the building analogy)

Imagine a building with a guard and a control room.

- **Suricata** on `soc-defender` is a camera. It watches the network and writes down anything that looks like an attack in `eve.json`.
- The **Wazuh agent** is the mail carrier. It reads the log files it was told to read and delivers them to the control room.
- **wazuh-server** is the control room, with three people:
  - **manager** — the analyst. Reads each message and decides: boring or important?
  - **indexer** — the archive. Stores everything so it can be searched.
  - **dashboard** — the screen I look at.

Why bother? Without a SIEM I would have to log into each machine and read its files. With Wazuh all the evidence is in one searchable place.

## 2. Decoders and rules

A log line arrives as raw text. Two steps turn it into an alert:

1. **Decoder** — reads the text and pulls out named fields (user, IP, port...). Like a clerk filling in a form from a messy letter.
2. **Rule** — looks at the filled-in form and decides if it matters, and how much (level 0–15).

Example from the SSH decoder: the regex catches three pieces of text, and `<order>user, srcip, srcport</order>` gives them names. The name `srcip` is not magic — the decoder author chose it, and Wazuh knows that field means "source IP".

Rules can build on each other. Suricata's rules in Wazuh are a small chain:

- `86600` (level 0): "this is a JSON line from Suricata" — the general door, no alert.
- `86601` (level 3): `if_sid 86600` + `event_type` is `alert` → "Suricata: Alert - <signature>". This is where my own rule's name shows up.

JSON logs go through Wazuh's generic `json` decoder, which keeps every field **under its original name** (`src_ip`, `dest_ip`, `alert.signature`...).

## 3. Rule IDs I met

| ID | Meaning |
|---|---|
| 86601 | Alert from Suricata (my sid 1000001 shows up as this) |
| 5710 | SSH login attempt with a user that does not exist (level 5) |
| 5712 | SSH brute force: 8 failures from the same IP in 120 s (level 10) |
| 5715 | SSH login success |
| 5402 | Successful `sudo` to root (it logged my own commands) |

## 4. Correlation

One alert alone is often harmless. A scan can be an admin tool. A failed login can be a typo. But **scan, then many failed logins, then a successful login, all from one IP within minutes** is a story: someone looked at the door, tried keys, and got in.

Correlation = linking events (same IP, close in time, in a meaningful order) into one story. It is what turns a pile of alerts into something an analyst can act on.

Wazuh can do this natively. Rule 5712 is a small example:

```xml
<rule id="5712" level="10" frequency="8" timeframe="120" ignore="60">
  <if_matched_sid>5710</if_matched_sid>
  <same_source_ip />
  ...
```

- `if_matched_sid` — the event being counted
- `frequency` + `timeframe` — how many times, in how many seconds
- `same_source_ip` — all from the same source IP
- `ignore` — after firing, stay quiet for 60 s so it does not flood

## 5. Why Wazuh could not link my two alerts

To say "same IP" it compares the standard field **`srcip`**. But:

- an SSH alert stores the IP as `data.srcip`
- a Suricata alert stores it as `data.src_ip`

Same value, different **name** — like two forms where one says "Name" and the other says "User". The comparison finds nothing in common.

The fix is a decoder that also writes `src_ip` into `srcip`. I tried three versions in `wazuh-logtest`; all failed (details in the phase 6 doc). So I did the linking in Python: take the IP from `srcip` **or** `src_ip`, whichever exists.

## 6. The tool I use to see what Wazuh does: `wazuh-logtest`

```bash
sudo /var/ossec/bin/wazuh-logtest
```

Paste one log line and it shows three phases:

- **Phase 1** pre-decoding
- **Phase 2** decoding — which fields were extracted
- **Phase 3** rules — which rule matched, its level, and whether an alert will be generated

It changes nothing on the real system, so I can test decoders and rules safely before restarting the manager.

## 7. The commands and code I used, explained

**Scan loop**

```bash
for p in $(seq 1 30); do timeout 1 bash -c "echo > /dev/tcp/10.10.10.20/$p" 2>/dev/null; done
```

- `for p in $(seq 1 30)` — repeat for p = 1…30
- `echo > /dev/tcp/HOST/PORT` — bash opens a TCP connection to that port (a SYN packet)
- `timeout 1` — give up after 1 second
- `2>/dev/null` — hide error messages

30 quick connection attempts = a tiny port scan that trips my Suricata rule.

**Failed SSH logins**

```bash
for i in $(seq 1 6); do
  ssh -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new fakeuser@10.10.10.20 true 2>/dev/null
done
```

- `fakeuser` does not exist, so every login fails
- `BatchMode=yes` — never ask for a password, just fail
- `ConnectTimeout=3` — wait at most 3 s
- `StrictHostKeyChecking=accept-new` — accept the server's key the first time without asking

This is a very small brute-force imitation.

**Python ideas in `correlate.py`**

- `defaultdict(list)` — a dictionary of lists, like a filing cabinet with one folder per attacker IP; a new IP gets an empty folder automatically.
- `datetime.strptime(...)` turns the text `2026-10-13T18:27:01` into a real time, so I can subtract two times and get seconds. Text cannot be subtracted.
- `(t - s).total_seconds()` — seconds between two events.
- `0 <= delta <= WINDOW` — the event must come **after** the scan and within the window.
- `for ... else` — the `else` runs only if the loop finished without `break`, i.e. no story was found for that IP.
- `get_ip()` — `data.get("srcip") or data.get("src_ip")` — the trick that unifies the two field names.

**Tuning knobs:** `WINDOW = 600`, `THRESHOLD = 3`, `SUCCESS_WINDOW = 3600`. Changing `SUCCESS_WINDOW` from 3600 to 600 dropped my test from `BREACH STORY` to `ATTACK STORY`.

## 8. What I would say about the limits

- The correlation runs outside Wazuh, by hand, on today's alerts only.
- It links by IP, so NAT or a changing attacker address can break the link.
- The numbers are my choices and I measured false positives only lightly.
- A patient attacker who waits longer than the window slips through — that is the evasion I want to test in phase 7.

## 9. Possible interview questions

**What is a SIEM and why use one?**
It collects logs from many machines into one place, applies rules to them, and lets an analyst search and see alerts. Without it you read logs machine by machine.

**Explain manager, indexer and dashboard.**
Manager analyses events with decoders and rules; indexer stores and searches them; dashboard is the web interface. The agent on each monitored machine sends logs to the manager.

**What is the difference between a decoder and a rule?**
A decoder extracts fields from raw text; a rule decides whether the decoded event matters and at what level.

**How did you connect Suricata to Wazuh?**
Suricata writes alerts as JSON to `eve.json`. I added a `<localfile>` block with `log_format json` to the agent's `ossec.conf`. The manager's built-in Suricata rules turn them into alerts (rule 86601).

**How did you prove it worked?**
I triggered my own scan rule (sid 1000001) and checked the same event in three places: Suricata's `fast.log`, Wazuh's `alerts.json`, and the dashboard.

**What is correlation and why does it matter?**
Linking related events into one story. Single alerts can be harmless; the sequence scan → failed logins → success from the same IP is what signals a real compromise.

**Why didn't you do the correlation inside Wazuh?**
Suricata and SSH alerts name the IP field differently (`src_ip` vs `srcip`), so `same_source_ip` could not match them. I tried custom decoders in `wazuh-logtest`; they either dropped the other fields or were rejected, so I wrote a Python script that unifies the names. A separate top-level decoder is something I'd still like to try.

**Your correlation rule caught something Wazuh's didn't — why?**
Rule 5712 needs 8 failures in 120 s. My test had 6, so it would not be expected to fire. My script looks at the sequence (scan, failures, success), not only the failure count.

**How would you tune it? What are the false positives?**
The window and thresholds control the trade-off. A short success window gave fewer false alarms but lost a patient attacker in my test; a long window catches him but may link unrelated events. I'd measure alerts on normal traffic over time before trusting any numbers.

**What did you do when the indexer failed to start?**
I did not just raise the timeout. I read the indexer log and the JVM log, ruled out RAM, disk and heap, and found kernel soft lockups across the whole VM at the time the host memory was at 95%. The most likely cause was host memory pressure. I changed the start procedure (close heavy apps, start the Wazuh VM first and alone).

**What are the weak points of your setup?**
Correlation is manual and external, links only by IP, covers one tested scenario, and the lab is small. The attacker was a VM in a closed network, and the management ports are reachable from the attack network — in a real SOC they would be separated and agent enrollment would use a password.
