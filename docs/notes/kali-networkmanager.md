# Kali Networking & NetworkManager — Learning Notes

Concepts I learned while connecting Kali to the lab. See [Phase 1 — Environment Setup](../phase-1-setup.md).

## NetworkManager

A **service** (a program always running in the background) that manages the network automatically: it detects network cards, asks DHCP for addresses, connects to Wi-Fi, and remembers networks it has joined.

It's like an app for the network: I **add**, **modify** and **activate** network configurations.

The Wi-Fi icon on a Linux desktop _is_ NetworkManager.

## Three ways to control it

| Interface    | How                        | When                    |
| ------------ | -------------------------- | ----------------------- |
| Desktop icon | mouse                      | on a desktop            |
| `nmtui`      | text menus in the terminal | easy, no mouse          |
| `nmcli`      | commands                   | scripts, SSH, precision |

All three control the same engine. **nmcli** = NetworkManager Command Line Interface.

## Device vs Connection

The most important idea:

- **Device** = the physical card: `eth0`, `eth1`, `wlan0`. It exists; I don't create it.
- **Connection** (or **profile**) = a sheet of settings: "use DHCP", "use 10.10.10.10", "join Wi-Fi X with password Y".

Analogy: the **device** is my phone; **connections** are the saved Wi-Fi networks (home, school, café). Many can be saved, but only **one connection is active per device** at a time.

Connections are stored as files, like netplan's YAML files. `nmcli con add` just writes one for me:

```bash
ls /etc/NetworkManager/system-connections/
sudo cat /etc/NetworkManager/system-connections/soclab.nmconnection
```

## Problem: Kali lost its internet connection

### What I noticed

After changing Kali's first network card from **Bridged** to **NAT** in VirtualBox, Kali had no internet:

- `ping 8.8.8.8` failed
- `ip a` showed that **neither** card (`eth0`, `eth1`) had an IPv4 address

### Why it happened

Kali has two network cards, each plugged into a different network:

| Card   | Plugged into | Is there a DHCP server there?       |
| ------ | ------------ | ----------------------------------- |
| `eth0` | NAT          | Yes: VirtualBox hands out addresses |
| `eth1` | soclab       | No: nobody hands out addresses      |

NetworkManager had only **one** settings profile, `Wired connection 1`, created automatically when Kali was installed. It said "get an address from DHCP", but it did **not** say which card it was for.

NetworkManager applied it to `eth1`:

- `eth1` asked for an address, but on soclab nobody answers, so it waited forever.
- `eth0`, the card that could actually get an address, had no profile at all, so it never asked.

**In one sentence:** a settings profile that isn't tied to a specific card can end up on the wrong one.

### How I confirmed it

Which profile is on which card (`DEVICE` column):

```bash
nmcli device status
```

```
eth1   connecting (getting IP configuration)   Wired connection 1
eth0   disconnected                             --
```

What is written inside a profile (`-f` = show only these fields):

```bash
nmcli -f connection.interface-name,ipv4.method con show "Wired connection 1"
```

| Field                       | Meaning                                                    |
| --------------------------- | ---------------------------------------------------------- |
| `connection.interface-name` | which card this profile is for (`--` = empty = any card)   |
| `ipv4.method`               | `auto` = ask DHCP for an address, `manual` = fixed address |

### The fix

```bash
# Write the card name on the DHCP profile, then activate it
sudo nmcli con modify "Wired connection 1" connection.interface-name eth0
sudo nmcli con up "Wired connection 1"

# Create a separate profile with a fixed address for eth1, then activate it
sudo nmcli con add type ethernet ifname eth1 con-name soclab ipv4.method manual ipv4.addresses 10.10.10.10/24
sudo nmcli con up soclab

# Check
nmcli device status
ping -c 2 8.8.8.8
ping -c 2 10.10.10.20
```

Final state:

| Profile            | `interface-name` | `ipv4.method` | Card   | Address                        |
| ------------------ | ---------------- | ------------- | ------ | ------------------------------ |
| Wired connection 1 | `eth0`           | `auto`        | `eth0` | 10.0.2.15, given by VirtualBox |
| soclab             | `eth1`           | `manual`      | `eth1` | 10.10.10.10, fixed             |

### Reproducing it (to practise)

To see the problem again on purpose:

```bash
sudo nmcli con down soclab                                                # eth1 has no settings
sudo nmcli con modify "Wired connection 1" connection.interface-name ""   # profile fits any card
sudo nmcli con up "Wired connection 1" ifname eth1                        # put it on eth1
```

The last command waits about 45 seconds, then fails. `nmcli device status` shows `eth0` disconnected and `ping 8.8.8.8` fails: a profile can be active on only **one card at a time**, so moving it to `eth1` took it away from `eth0`.

Then apply **The fix** above to get back to normal.

### Lesson

On a machine with several network cards:

- **tie every profile to its card** (`connection.interface-name`)
- use **fixed addresses** on networks that have no DHCP server

## Connection names and UUID

`Wired connection 1` is **just a name**, a default NetworkManager generated automatically. The real identity of a connection is its **UUID** (unique ID, visible in `nmcli con show`). The name is for humans, the UUID is for the system.

A connection can be renamed to describe its role:

```bash
sudo nmcli con modify "Wired connection 1" connection.id nat
```

Quotes are only needed when the name contains spaces.

Best practice: **name things by what they do** (`nat`, `soclab`), so they're recognizable at a glance.

## nmcli command structure

```
nmcli  <object>  <command>  <arguments>
```

| Object               | Works on                     |
| -------------------- | ---------------------------- |
| `device` / `dev`     | network cards                |
| `connection` / `con` | settings sheets (profiles)   |
| `general`            | NetworkManager overall state |

### Daily commands

```bash
nmcli device status          # state of every card and which connection it uses
nmcli con show               # saved connections (with UUIDs)
nmcli con show --active      # only active connections
nmcli con show soclab        # all settings of one connection
sudo nmcli con up soclab     # activate
sudo nmcli con down soclab   # deactivate
```

### Creating and modifying

```bash
sudo nmcli con add type ethernet ifname eth1 con-name soclab ipv4.method manual ipv4.addresses 10.10.10.10/24
```

| Part                            | Meaning                 |
| ------------------------------- | ----------------------- |
| `con add`                       | create a new connection |
| `type ethernet`                 | for a wired card        |
| `ifname eth1`                   | apply it to this device |
| `con-name soclab`               | its name (my choice)    |
| `ipv4.method manual`            | no DHCP, static address |
| `ipv4.addresses 10.10.10.10/24` | the address             |

```bash
sudo nmcli con modify "Wired connection 1" connection.interface-name eth0
```

`connection.interface-name` is the full property name; `ifname` is a shortcut allowed with `add`.

**`modify` only edits the settings sheet.** The change applies only after `sudo nmcli con up <name>`.

Other useful commands:

```bash
sudo nmcli con delete soclab                        # remove a connection
nmcli device wifi list                              # nearby Wi-Fi networks
nmcli device wifi connect "MyWiFi" password "..."   # join Wi-Fi from the terminal
```

## Where NetworkManager is used

- Kali, Ubuntu Desktop and most desktop distributions
- Red Hat, CentOS, Rocky, Fedora: the official tool, **even on servers** (common in companies)
- In pentesting: change IP quickly, switch networks, join Wi-Fi from the terminal

## Ubuntu Server vs Kali

|       | Ubuntu Server                | Kali                                      |
| ----- | ---------------------------- | ----------------------------------------- |
| Tool  | netplan (+ systemd-networkd) | NetworkManager                            |
| How   | write a YAML file by hand    | run an nmcli command (it writes the file) |
| Apply | `sudo netplan apply`         | `sudo nmcli con up <name>`                |

Same goal, different tool. **Never install NetworkManager on the Ubuntu Server**: it would fight netplan over the same cards.

## Testing connectivity in stages

Each test checks a different layer, so a failure points to one cause:

```bash
ip a                    # does the card have an IP?
nmcli device status     # which connection is on which card?
ping -c 2 8.8.8.8       # internet by IP → routing works
ping -c 2 google.com    # by name → DNS works
ping -c 4 10.10.10.20   # lab target → soclab works
```

If `8.8.8.8` works but `google.com` fails, the problem is DNS only.

`ping -c 4` = **count**: send 4 packets then stop (without `-c`, it runs until Ctrl+C).

## ARP and "Destination Host Unreachable"

Before sending anything to `10.10.10.20`, Kali needs its **MAC address**. It broadcasts an **ARP** request to the whole network: "who has 10.10.10.20?"

If nobody answers (the target is off, or not on the same network), Kali gives up and reports **itself**:

```
From 10.10.10.10 icmp_seq=1 Destination Host Unreachable
```

The ARP table shows what the machine knows about IP → MAC:

```bash
ip neigh show 10.10.10.20    # FAILED / INCOMPLETE = ARP got no reply
```

This is the same ARP I will attack in Phase 4 (ARP spoofing).

Lesson: **check the simplest cause first**, like whether the other machine is even on.

## TTL and latency

```
64 bytes from 10.10.10.20: icmp_seq=1 ttl=64 time=2.98 ms
```

- **TTL (Time To Live):** Linux starts at 64; every router on the path subtracts 1. Still 64 → direct link, no router in between. Windows usually starts at 128, so TTL also hints at the target's OS (used in scans).
- **time:** ~2 ms on soclab because traffic never leaves my PC; ~530 ms to `google.com` because it crosses the internet.

## Shell variables and `echo`

- `$` means "give me the **value** of this variable".
- `echo` is the command that **prints** it.

Without `echo`, the shell replaces the variable and tries to run its value as a command:

```
$ $SSH_CONNECTION
10.10.10.10: command not found
```

A misspelled variable (`$SSH_CONECTION`) prints an **empty line with no error**. Empty output where I expect a value → check the spelling.

## Knowing where I am

With several machines and SSH sessions open, the **prompt** is the only thing telling me where a command will run:

```
inspiplease@inspiplease   → Kali
a5rasx@soc-defender       → the defender (via SSH)
```

Always read it before running a command. `exit` leaves the SSH session and returns to the previous machine.

## dpkg

**dpkg** is the low-level tool `apt` uses to install packages. If an installation is interrupted (VM shut down, updates cancelled), packages stay half-configured and every future install fails with `dpkg was interrupted`.

```bash
sudo dpkg --configure -a     # finish configuring all half-installed packages (-a = all)
```

## Learning tools without memorizing everything

Nobody memorizes every command. What matters:

1. **Concepts**: device vs connection, DHCP vs static, reading `ip a`, diagnosing by IP first then by name. These are what interviews ask about.
2. **A few daily commands.**
3. **Everything else in my notes.**
4. **Knowing where to look:**

| How                 | Example                                                          |
| ------------------- | ---------------------------------------------------------------- |
| **Tab** twice       | `nmcli con ` + Tab Tab → lists possible options                  |
| Built-in help       | `nmcli con --help`                                               |
| Manual              | `man nmcli` (quit with `q`)                                      |
| Ready-made examples | `man nmcli-examples`                                             |
| Filter output       | `nmcli con show soclab \| grep ipv4` (like `findstr` on Windows) |

An interview won't ask me to type `nmcli con add` from memory. It will ask: "a machine has no internet, how do you diagnose it?", and I've lived that scenario.