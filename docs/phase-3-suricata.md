# Phase 3 — Suricata IDS: Detecting the Scan

## Goal
In Phase 2 a port scan left **no trace** in `auth.log`. This phase answers: how do you detect a network attack that log files are blind to? The answer is an **IDS** watching the network itself. We install Suricata, configure it, write our own detection rule, and catch the scan.

## Why an IDS
`auth.log` is written by the **sshd** application and only records authentication events (login attempts). A port scan never tries to log in — it stops at the network layer — so `auth.log` never sees it. An **IDS (Intrusion Detection System)** sits on the network and inspects every packet, so it sees what the application layer misses. It **detects and alerts** but does not block (blocking = IPS, a later phase).

## Step 1 — Install
```bash
sudo apt install suricata -y
suricata -V          # note: -V (capital), not --version, on Suricata 8
```
Version installed: 8.0.3.

## Step 2 — Back up the config before editing
```bash
sudo cp /etc/suricata/suricata.yaml /etc/suricata/suricata.yaml.bak
```
`cp` = copy. The `.bak` copy lets me restore the original with one command if I break something. **Habit: always back up an important config before editing it.**

## Step 3 — Configure `suricata.yaml`
The main config file. The keys that matter for this lab:

| Key | Purpose | Value set |
|-----|---------|-----------|
| `HOME_NET` | the network I protect | `[10.10.10.0/24]` |
| `EXTERNAL_NET` | everything that isn't HOME_NET | left as `!$HOME_NET` |
| `af-packet: interface` | which card Suricata watches | `enp0s8` (the soclab card, where attacks arrive) |
| `default-rule-path` | folder Suricata looks in for rules | `/var/lib/suricata/rules` |
| `rule-files` | list of rule files to load | `suricata.rules`, `local.rules` |
| `outputs` | where/how logs are written | defines `fast.log`, `eve.json`, etc. |

I watch `enp0s8` and not `enp0s3` (NAT) because the attacks come from Kali over the soclab. To read the file calmly without editing: `less /etc/suricata/suricata.yaml` (search with `/`, quit with `q`).

## Step 4 — Load a rule set
A fresh Suricata has eyes but no list of what to watch for. Rules are that list. First a test showed:
```
Warning: No rule files match the pattern /var/lib/suricata/rules/suricata.rules
```
So I downloaded the free **ET Open** rule set:
```bash
sudo suricata-update
```
After that: `52992 rules successfully loaded`.

## Step 5 — Test the config before running
```bash
sudo suricata -T -c /etc/suricata/suricata.yaml -v
```
`-T` = **test mode**: Suricata does all the preparation (reads the config, loads every rule, checks everything is valid) then exits **without watching anything**. It answers one question — "is my setup valid?" — and catches errors *before* a real start, exactly like `netplan try`. `-c` = which config file, `-v` = verbose. Success ends with `Configuration provided was successfully loaded. Exiting.`

## Step 6 — Run as a service
```bash
sudo systemctl enable --now suricata      # start now + on every boot
sudo systemctl status suricata            # expect: active (running)
```
The log confirmed it started a worker on the right card:
```
[W#01-enp0s8] ... Info: ioctl: enp0s8: MTU 1500
```

## Step 7 — Attack, and the first surprise: no alert
```bash
# defender: watch alerts live
sudo tail -f /var/log/suricata/fast.log
# Kali
nmap 10.10.10.20
```
**Nothing appeared.** Suricata was working, but the default ET Open rules don't alert on a simple fast scan (it would cause too many false positives in real networks). This is normal — and the reason we write our **own** rule.

## Step 8 — Confirm Suricata actually sees the traffic
Before blaming the rule, prove Suricata sees the packets. `eve.json` logs **every** event, so:
```bash
sudo tail -f /var/log/suricata/eve.json     # then scan from Kali
```
It filled with lines like:
```json
{"in_iface":"enp0s8","event_type":"flow","src_ip":"10.10.10.10","dest_ip":"10.10.10.20","dest_port":525,
 "tcp":{"syn":true,"rst":true,"ack":true,...,"alerted":false}}
```
So Suricata **sees** the scan (`in_iface: enp0s8`, `src_ip: 10.10.10.10`, `syn:true`, many different `dest_port`) but `alerted:false` — no rule matched. The problem is the rule, not the capture.

## Step 9 — Write our own rule
The rule file lives where `default-rule-path` points — `/var/lib/suricata/rules/`, **not** `/etc/suricata/rules/`. (I first created it in `/etc/...`, Suricata couldn't find it, and I moved it with `mv`.)
```bash
sudo nano /var/lib/suricata/rules/local.rules
```
Final working rule:
```
alert tcp any any -> $HOME_NET any (msg:"LOCAL Nmap TCP scan detected"; flow:to_server; flags:S+; threshold:type both, track by_src, count 15, seconds 10; sid:1000001; rev:3;)
```
Then tell Suricata to load it, in `suricata.yaml` under `rule-files`:
```yaml
rule-files:
  - suricata.rules
  - local.rules
```
Test, then restart:
```bash
sudo suricata -T -c /etc/suricata/suricata.yaml -v     # expect rule count +1
sudo systemctl restart suricata
```

## Step 10 — Catch the scan
```bash
# defender
sudo tail -f /var/log/suricata/fast.log
# Kali
sudo nmap -sS -p 1-1000 10.10.10.20
```
Result — one clean alert per scan:
```
[1:1000001:3] LOCAL Nmap TCP scan detected {TCP} 10.10.10.10:41426 -> 10.10.10.20:445
```
Compared with Phase 2:
| Attack | auth.log | Suricata (our rule) |
|--------|----------|---------------------|
| Port scan | ❌ silent | ✅ clear alert |

**This is the core of SOC work, built by hand: attack → notice the ordinary tools are blind → put a sensor on the network → write a detection rule → catch it.**

## Problems & Fixes
- **`suricata --version` → unrecognized option**
  Cause: Suricata 8 uses the short form. Fix: `suricata -V`.

- **`No rule files match ... suricata.rules` warning**
  Cause: no rules downloaded yet. Fix: `sudo suricata-update`.

- **Rule file created but not loaded**
  Cause: I wrote it in `/etc/suricata/rules/`, but Suricata searches `default-rule-path` = `/var/lib/suricata/rules/`. Fix: `sudo mv /etc/suricata/rules/local.rules /var/lib/suricata/rules/`.

- **Rule didn't match even though Suricata saw the SYNs (`flags:S`)**
  Cause: `flags:S` means "SYN and nothing else". In the flow, packets carried SYN together with other flags, so the strict match failed. Fix: `flags:S+` = "SYN present, other flags allowed".

- **Rule with `$EXTERNAL_NET` never fired**
  Cause: in this lab the attacker (Kali, 10.10.10.10) is **inside** HOME_NET (10.10.10.0/24), so it isn't "external". Fix: use `any` as the source. Lesson: when the attacker shares the subnet, don't rely on `$EXTERNAL_NET`.

- **Test rule was too noisy (one alert per SYN)**
  Cause: no `threshold`, so it alerted on every single SYN including normal traffic. Fix: the real rule uses a `threshold` to alert only on a burst, and only once.

## Screenshots
- [ ] `suricata -T` success (config + rules valid)
- [ ] `eve.json` during the scan (Suricata sees the SYNs, `alerted:false`)
- [ ] `fast.log` with the `LOCAL Nmap TCP scan detected` alert
- [ ] side by side: nmap in Kali + the alert on the defender