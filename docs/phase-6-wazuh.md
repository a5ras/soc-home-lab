# Phase 6 — Wazuh (SIEM) and Suricata integration

## Goal

Bring all the lab's detection output into one place. Until phase 5, Suricata alerts lived in log files on `soc-defender`. In this phase I installed Wazuh on its own VM, connected `soc-defender` to it, and made my own Suricata rule (sid 1000001) show up as an alert in the Wazuh dashboard. Then I tried to go one step further: **correlate** a port scan, failed SSH logins and a successful login from the same IP into one attack story.

**Short result:** the Suricata → Wazuh pipeline works and is verified end to end. The correlation works too, but as an external Python script, not as a Wazuh rule. I tried the Wazuh-native way first and it failed; the details are in *Problems & Fixes*.

## Architecture

```
        VirtualBox internal network "soclab" (10.10.10.0/24)

  wazuh-server (10.10.10.40)      soc-defender (10.10.10.20)      Kali (10.10.10.10)
  ┌───────────────────────┐       ┌─────────────────────────┐     attacker
  │ wazuh-manager         │◄──────│ wazuh-agent             │
  │ wazuh-indexer         │ logs  │ Suricata (IDS) ──► eve.json
  │ wazuh-dashboard (443) │       │ sshd                    │
  └───────────────────────┘       └─────────────────────────┘
   dashboard reached from Windows at https://127.0.0.1:8443 (NAT port forward 8443 → 443)
   SSH to wazuh-server from Windows via NAT port forward 2240 → 22
```

| Item | Value |
|---|---|
| Wazuh version | 4.14.8, all-in-one install (manager + indexer + dashboard on one VM) |
| wazuh-server | Ubuntu Server, 4 GB RAM, 2 vCPU, 50 GB disk, static IP 10.10.10.40 on `soclab` |
| Agent | wazuh-agent 4.14.8 on `soc-defender` (name `soc-defender`, manager 10.10.10.40) |
| Host | Windows, 8 GB RAM, VirtualBox |

## What I did

### 1. wazuh-server VM and network
Created a new VM `wazuh-server`. Adapter 1 is NAT (for downloads and for the port forwards), Adapter 2 is the internal network `soclab` with a static IP set in netplan (`60-soclab.yaml`). I checked that it can ping `soc-defender` and reach the internet.

### 2. Install Wazuh
Ran the official all-in-one installer (flags `-a -i`). After the install I disabled the Wazuh apt repository so the stack is not updated by accident, and removed the temporary bridged adapter used for the download (see Problems & Fixes). The dashboard opened at `https://127.0.0.1:8443`.

### 3. Agent on soc-defender
Installed `wazuh-agent` 4.14.8 on `soc-defender`, pointed it at 10.10.10.40, and confirmed it shows as **Active** in the dashboard.

### 4. Connect Suricata to Wazuh
Suricata already writes every event as one JSON object per line in `/var/log/suricata/eve.json`. The agent only reads files it is told to read, so I added one block to `/var/ossec/etc/ossec.conf` on `soc-defender` (backup first: `ossec.conf.bak`):

```xml
<ossec_config>
  <localfile>
    <log_format>json</log_format>
    <location>/var/log/suricata/eve.json</location>
  </localfile>
</ossec_config>
```

Then `sudo systemctl restart wazuh-agent`. The manager already ships rules for Suricata (`0475-suricata_rules.xml`), so nothing was needed on the manager side.

### 5. Prove it end to end
From `wazuh-server` (to save RAM I did not start Kali) I generated a fast scan against `soc-defender`:

```bash
for p in $(seq 1 30); do timeout 1 bash -c "echo > /dev/tcp/10.10.10.20/$p" 2>/dev/null; done
```

This trips my own rule (sid 1000001, 15 SYN packets in 10 seconds). Suricata logged it in `fast.log`, and Wazuh produced alerts with `rule.id 86601` (*"Suricata: Alert - LOCAL Nmap TCP scan detected"*), agent `soc-defender`, `10.10.10.40 → 10.10.10.20`. They are visible in Threat Hunting with the query `rule.groups:suricata`.

### 6. Correlation
Goal: flag **scan → failed SSH logins → successful SSH login, all from the same IP**.

First I looked at what Wazuh stores for each event type:

| | Suricata alert | SSH failed login |
|---|---|---|
| Rule | 86601 (level 3) | 5710 (level 5, "non-existent user") |
| Attacker IP field | `data.src_ip` | `data.srcip` |

The IP is the same value, but the **field name differs**. Wazuh's `same_source_ip` option compares the standard `srcip` field, so a native correlation rule would not link the two. (Details in Problems & Fixes.)

So I wrote `correlate.py`, built in four steps (list events → group by IP → scan + failures → scan + failures + success). It reads `/var/ossec/logs/alerts/alerts.json`, takes the IP from `srcip` or `src_ip`, groups events per IP, and applies this rule:

- a scan (rule 86601), then
- at least `THRESHOLD = 3` failed SSH events within `WINDOW = 600` s of the scan, then
- a successful SSH login (rule 5715) within `SUCCESS_WINDOW = 3600` s of the last failure.

A scan plus enough failures → `ATTACK STORY`. All three links → `BREACH STORY`.

**Test.** From `wazuh-server` I ran a scan, 6 failed SSH logins with a user that does not exist (`fakeuser`), then one successful login with a real account. Output:

```
no story for 10.0.2.2
BREACH STORY from 10.10.10.40
  1. scan at 2026-10-13 18:27:01
  2. 6 failed SSH logins within 600 seconds
  3. successful login at 2026-10-13 19:10:13
```

`10.0.2.2` is the address under which `soc-defender`/`wazuh-server` see my Windows host through the VirtualBox NAT. My own normal login from Windows produced no story, as it should.

**Sensitivity test.** The successful login happened about 38 minutes after the last failure. With `SUCCESS_WINDOW = 600` the same events gave only `ATTACK STORY`: the third link was lost. Lesson: a short window gives fewer false alarms but a patient attacker slips through; a long window catches the patient attacker but links more unrelated events.

**Why the script caught something Wazuh did not.** Wazuh's built-in brute-force rule 5712 needs 8 failures in 120 seconds from one IP (`frequency="8" timeframe="120"`). My test used 6 failures, so that rule would not be expected to fire (I did not check whether it fired). The script looks at the *sequence*, not only the count.

## Problems & Fixes

**1. Install ran out of disk space.** The first disk was 25 GB; the Wazuh install failed and rolled back. *Fix:* enlarge the disk. Final size: 50 GB (about 48 GB usable root).

**2. Resizing a snapshot's child disk did not really work.** The resize looked successful but writes past 25 GB failed and paused the VM. *Fix:* restore, delete the snapshot `phase-6-network-ready`, and resize the single base disk. *Lesson:* resize the base disk, not a snapshot's differencing disk.

**3. VirtualBox NAT was very slow.** About 8 MB/min for downloads, while the host has a fast connection. *Fix:* a temporary bridged adapter (`enp0s9`) for the install (about 24 MB/s), removed afterwards.

**4. After a reboot the manager came up with failed daemons ("No API available").** *Fix:* `sudo systemctl restart wazuh-manager`.

**5. `wazuh-indexer` failed to start with `Result: timeout`.**
- First guess: slow start. I added a systemd override `TimeoutStartSec=300` for the indexer and manager. The indexer still failed, so it was not just slowness.
- Ruled out: RAM inside the VM (2.4 GB available), disk (26 GB free), JVM heap (1 GB, GC healthy: heap use about 65 MB at the end, pauses around 40 ms).
- The evidence: the indexer log went silent for about 7 minutes; the JVM log showed a safepoint that took about 427 seconds to leave; `dmesg` showed `soft lockup - CPU#0 stuck for 398s` and `CPU#1 stuck for 398s`, and systemd's watchdog killed `journald`, `logind`, `snapd`, `udevd` and `resolved` at the same moment. So the **whole VM froze**, not just Wazuh.
- At that time Task Manager showed the Windows host memory at **95%** (Chrome, Discord, Steam plus the VMs on an 8 GB machine). **Most likely cause: host memory pressure.** I did not prove it with a controlled test; the evidence is the timing, the whole-VM freeze, and the fact that the indexer started normally on the next attempt.
- *Fix / procedure:* close Chrome, Discord and Steam before starting the lab; start `wazuh-server` alone first and wait until all three services are active; then start `soc-defender`. Take the snapshot only with the VMs powered off.

**6. Duplicated `<localfile>` block in `ossec.conf`.** I pasted the block twice, which would make the agent watch the same file twice and could duplicate alerts. Caught by looking at the file before testing. *Fix:* removed the copy, then verified with `grep -c "eve.json" ossec.conf` → `1`. *Lesson:* always re-read a config file after editing it.

**7. The dashboard showed 2 of 3 alerts.** The time filter was `22:00–22:30`, and the third alert was later. Not a bug: widen the time range. (Also note the UI and the logs use different time zones.)

**8. `grep` found itself.** Searching `alerts.json` with `grep 1000001` returned an alert for `sudo` (rule 5402, "Successful sudo to ROOT", MITRE T1548.003) because Wazuh had logged my own `sudo grep 1000001 ...` command. Lesson: filter on parsed fields (`rule.id`), not on raw text; and a nice reminder that the SIEM also sees the administrator.

**9. First Python check crashed with `'NoneType' object is not subscriptable`.** The script found no Suricata alert at all. Likely explanation (not verified): Wazuh starts a new `alerts.json` each day and the earlier alerts were archived. *Fix:* generate a fresh scan, and make the script handle "nothing found".

**10. Making Wazuh itself link the two events (failed).** Idea: write a custom decoder that copies Suricata's `src_ip` into the standard `srcip` field, so `same_source_ip` could work. I tested each version in `wazuh-logtest` before applying it:

| Attempt | Result |
|---|---|
| One child decoder of `json` with a regex and `<order>srcip</order>` | `srcip` appeared, but all the other JSON fields disappeared, so rule 86601 no longer matched |
| Two sibling child decoders (one with `JSON_Decoder` plugin, one with the regex) | Fields came back, but `srcip` was missing: only the first matching child seemed to run |
| A child of the child decoder | `ERROR: (2101): Parent decoder name invalid` — nested children are not allowed |

I restored `local_decoder.xml` from the backup, checked that it contained no leftover decoder, and checked that `wazuh-logtest` still matched rule 86601. The route that probably works (a separate top-level decoder with its own prematch) I did not finish; I moved to the Python script instead. *Lesson:* test decoders in `wazuh-logtest` before restarting anything, and always keep a backup of `local_decoder.xml`.

## Limits (what this does not do)

- `correlate.py` is run **by hand** and is **not a Wazuh rule**: the story does not appear in the dashboard. The idea for later: have the script write its verdict to a log file, read it with a `<localfile>`, and add a custom rule.
- It reads only today's `alerts.json`.
- It links events by IP address. Behind NAT or with a changing attacker address it would miss the link.
- The thresholds (600 s, 3 failures, 3600 s) are my choices; I have not measured false positives beyond one sensitivity test.
- Only one scenario was tested, and the "attacker" was `wazuh-server`, not Kali, to save RAM. The attack was a simulated one in a closed lab.
- Security note: from Kali on `soclab` the dashboard (443) and the agent enrollment port (1515) are reachable. In a real SOC the management network would be separate and agent enrollment would use a password.

## MITRE ATT&CK

| Technique | Where it appears | Source |
|---|---|---|
| T1110 Brute Force | rule 5712 metadata | Wazuh |
| T1548.003 Sudo and Sudo Caching | rule 5402 on my own `sudo` | Wazuh |
| T1046 Network Service Discovery (scan) | the scan stage | my mapping, Wazuh does not tag it |
| T1078 Valid Accounts (successful login) | the third stage | my mapping, Wazuh does not tag it |

## Evidence

Some steps were saved as text output instead of screenshots (my PC was not capturing screens at that point):

- `evidence/phase-6/correlate.py` — the final script
- `evidence/phase-6/correlate-breach-story.txt` — its output

<!-- TODO: add the phase-6 screenshots from images/phase-6/ here -->

## Snapshots

`phase-6-suricata-wazuh` on both `wazuh-server` and `soc-defender`, taken with the VMs powered off.

## Next

Phase 7: two more attacks with the full chain (execute → understand → see in logs → write detection → try to evade → defend), including trying to evade the correlation rule by waiting, and the final documentation. Optional: feed the correlation verdict back into Wazuh as a real alert.
