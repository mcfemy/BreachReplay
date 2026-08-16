"""
Static, hand-curated MITRE ATT&CK technique dossier for the five flagship
scenarios (Colonial Pipeline, SolarWinds, MGM Resorts, Log4Shell, NHS
WannaCry). Researched and cited to the real incidents (CISA AA21-131A,
CISA AA20-352A, NCSC WannaCry reporting, Log4Shell CVE-2021-44228
advisories, and public reporting on the 2023 MGM/Scattered Spider
intrusion); kept as a plain constant here rather than a DB table since
it's technique-scoped reference content shared across scenarios (e.g.
T1078 appears in both Colonial Pipeline and SolarWinds), not a
per-scenario row field like Scenario.mitre_techniques (backend/seed.py).

T1078.001 is deliberately included even though seed.py's
COLONIAL_PIPELINE.mitre_techniques only tags the parent T1078 — the
scenario-level array is coarser than the actual decision-gate/incident
detail; this dossier's attacker-stage progression tags it as a distinct
stage.

nhs-gate-004 is tagged T1190 in seed.py for a reason unrelated to its
usual "exploited public-facing app" meaning here — see that entry's
incident_narrative for the real MalwareTech kill-switch context.
"""

TECHNIQUE_DOSSIER: dict[str, dict] = {
    "T1078": {
        "name": "Valid Accounts",
        "scenarios": ["colonial_pipeline", "solarwinds"],
        "tactic": "Defense Evasion, Persistence, Privilege Escalation, Initial Access",
        "description": (
            "Adversaries authenticate using legitimate, stolen credentials instead of "
            "exploiting a vulnerability, avoiding exploit-based detection."
        ),
        "incident_narrative": (
            "DarkSide's affiliates got into Colonial's network through a single legacy "
            "VPN account with a leaked password and no MFA. In SolarWinds, once inside "
            "via the supply-chain compromise, attackers authenticated as legitimate "
            "users to blend into normal traffic."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1078",
    },
    "T1078.001": {
        "name": "Valid Accounts: Default Accounts",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Defense Evasion, Persistence, Privilege Escalation, Initial Access",
        "description": (
            "Pre-configured or factory-default credentials never rotated; "
            "devices/legacy systems often retain well-known logins nobody changes."
        ),
        "incident_narrative": (
            "The VPN account DarkSide used had been disabled from active use but never "
            "fully decommissioned — a \"dead\" account still technically valid."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1078.001",
    },
    "T1003": {
        "name": "OS Credential Dumping",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Credential Access",
        "description": (
            "Adversaries extract stored credentials (password hashes, cached logins) "
            "directly from memory or disk, turning one compromised account into many."
        ),
        "incident_narrative": (
            "This is the step that turned \"one leaked VPN password\" into broader "
            "domain access during the Colonial intrusion."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1003",
    },
    "T1136": {
        "name": "Create Account",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Persistence",
        "description": (
            "Adversaries create their own account on a compromised system/domain for a "
            "durable foothold that survives the original entry point being locked out."
        ),
        "incident_narrative": (
            "Standard DarkSide affiliate tradecraft during the Colonial intrusion to "
            "maintain access."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1136",
    },
    "T1021": {
        "name": "Remote Services",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Lateral Movement",
        "description": (
            "Using legitimate remote-access protocols (RDP, SSH, SMB admin shares) to "
            "move between systems using the same tools IT teams use."
        ),
        "incident_narrative": (
            "Lateral movement technique used across the Colonial network following "
            "initial VPN access."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1021",
    },
    "T1053": {
        "name": "Scheduled Task/Job",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Execution, Persistence, Privilege Escalation",
        "description": (
            "Adversaries set up scheduled tasks for persistence or to trigger payloads "
            "at a specific time without needing to stay actively connected."
        ),
        "incident_narrative": (
            "Used to establish persistence ahead of the ransomware deployment in the "
            "Colonial intrusion."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1053",
    },
    "T1041": {
        "name": "Exfiltration Over C2 Channel",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Exfiltration",
        "description": (
            "Data is stolen out over the same command-and-control channel already used "
            "to control the compromise."
        ),
        "incident_narrative": (
            "DarkSide exfiltrated roughly 100GB of Colonial's data before deploying "
            "ransomware — the double-extortion playbook: steal first, encrypt second."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1041",
    },
    "T1486": {
        "name": "Data Encrypted for Impact",
        "scenarios": ["colonial_pipeline", "mgm_resorts", "nhs_wannacry"],
        "tactic": "Impact",
        "description": (
            "The ransomware payload itself — files, databases, systems encrypted and "
            "held for ransom."
        ),
        "incident_narrative": (
            "Colonial: DarkSide's ransomware deployment that triggered the shutdown. "
            "MGM: deployed in partnership with ALPHV/BlackCat, hitting slot machines, "
            "hotel key systems, and reservations. NHS WannaCry: encrypted files across "
            "infected NHS systems via a self-propagating worm rather than a targeted "
            "intrusion, producing a much larger and faster blast radius."
        ),
        "source_reference": "CISA AA21-131A; NCSC WannaCry report; MITRE ATT&CK T1486",
    },
    "T1562.001": {
        "name": "Impair Defenses: Disable or Modify Tools",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Defense Evasion",
        "description": (
            "Adversaries disable security tooling (EDR, antivirus, logging) so activity "
            "goes unrecorded and payloads run unopposed."
        ),
        "incident_narrative": (
            "Used ahead of ransomware deployment in the Colonial intrusion to blind "
            "defenders."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1562.001",
    },
    "T1490": {
        "name": "Inhibit System Recovery",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Impact",
        "description": (
            "Deleting shadow copies, disabling recovery features, wiping backup "
            "catalogs so victims can't restore without paying."
        ),
        "incident_narrative": (
            "Standard DarkSide ransomware tradecraft to remove Colonial's ability to "
            "recover without engaging the ransom demand."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1490",
    },
    "T1565.001": {
        "name": "Data Manipulation: Stored Data Manipulation",
        "scenarios": ["colonial_pipeline"],
        "tactic": "Impact",
        "description": "Tampering with data at rest to influence a decision or hide activity.",
        "incident_narrative": (
            "DarkSide never touched Colonial's OT/pipeline control systems — "
            "billing/IT systems were compromised, and Colonial chose to shut the "
            "pipeline down as a precaution because they couldn't verify billing "
            "accuracy or intrusion scope. The physical outage was a business decision "
            "made under uncertainty, not a direct technical consequence."
        ),
        "source_reference": "CISA AA21-131A; MITRE ATT&CK T1565.001",
    },
    "T1195.002": {
        "name": "Supply Chain Compromise: Compromise Software Supply Chain",
        "scenarios": ["solarwinds"],
        "tactic": "Initial Access",
        "description": (
            "Adversaries compromise a trusted vendor so the victim's own update "
            "mechanism delivers the malware."
        ),
        "incident_narrative": (
            "APT29 compromised SolarWinds' Orion build process via the SUNSPOT "
            "implant, inserting a backdoor into a legitimately signed update ~18,000 "
            "organizations installed voluntarily."
        ),
        "source_reference": "CISA AA20-352A; MITRE ATT&CK T1195.002",
    },
    "T1558.001": {
        "name": "Steal or Forge Kerberos Tickets: Golden Ticket",
        "scenarios": ["solarwinds"],
        "tactic": "Credential Access",
        "description": (
            "Forging a Kerberos ticket using a stolen domain key grants access to "
            "anything in the domain, as any user, without touching the domain "
            "controller again."
        ),
        "incident_narrative": (
            "The \"Golden SAML\" escalation move that made SolarWinds' "
            "identity-federation compromise so severe — attackers could impersonate "
            "any user, including admins, across federated cloud services."
        ),
        "source_reference": "CISA AA20-352A; MITRE ATT&CK T1558.001",
    },
    "T1048.002": {
        "name": "Exfiltration Over Alternative Protocol: Asymmetric Encrypted Non-C2 Protocol",
        "scenarios": ["solarwinds"],
        "tactic": "Exfiltration",
        "description": (
            "Stealing data over a channel separate from the main C2 connection, "
            "encrypted in a way that doesn't match normal C2 traffic patterns."
        ),
        "incident_narrative": (
            "Used to defeat network monitoring tuned to catch standard C2 beaconing "
            "during the SolarWinds intrusion."
        ),
        "source_reference": "CISA AA20-352A; MITRE ATT&CK T1048.002",
    },
    "T1070.004": {
        "name": "Indicator Removal: File Deletion",
        "scenarios": ["solarwinds"],
        "tactic": "Defense Evasion",
        "description": (
            "Deleting tools, logs, or staged files after use to remove forensic "
            "evidence."
        ),
        "incident_narrative": (
            "Used by the SolarWinds attackers to prevent investigators from "
            "reconstructing the full intrusion timeline."
        ),
        "source_reference": "CISA AA20-352A; MITRE ATT&CK T1070.004",
    },
    "T1059.003": {
        "name": "Command and Scripting Interpreter: Windows Command Shell",
        "scenarios": ["solarwinds"],
        "tactic": "Execution",
        "description": (
            "Using cmd.exe and native Windows tooling to execute commands, living off "
            "the land instead of dropping custom malware."
        ),
        "incident_narrative": (
            "Used during the SolarWinds post-compromise phase to avoid antivirus "
            "detection."
        ),
        "source_reference": "CISA AA20-352A; MITRE ATT&CK T1059.003",
    },
    "T1071.001": {
        "name": "Application Layer Protocol: Web Protocols",
        "scenarios": ["solarwinds", "log4shell"],
        "tactic": "Command and Control",
        "description": (
            "C2 traffic disguised as ordinary HTTP/HTTPS traffic, blending into normal "
            "web-request noise."
        ),
        "incident_narrative": (
            "SUNBURST's C2 traffic mimicked SolarWinds' own legitimate Orion "
            "Improvement Program network traffic patterns, deliberately shaped to not "
            "look anomalous."
        ),
        "source_reference": "CISA AA20-352A; MITRE ATT&CK T1071.001",
    },
    "T1078.004": {
        "name": "Valid Accounts: Cloud Accounts",
        "scenarios": ["solarwinds"],
        "tactic": "Defense Evasion, Persistence, Privilege Escalation, Initial Access",
        "description": (
            "The cloud-specific version of Valid Accounts — compromising Azure AD, AWS "
            "IAM, or similar cloud identity accounts."
        ),
        "incident_narrative": (
            "Let the SolarWinds intrusion jump from on-prem networks into victims' "
            "cloud environments (notably Microsoft 365/Azure AD), turning a single "
            "on-prem compromise into cross-environment access — the step that made "
            "this a federal-government-scale incident."
        ),
        "source_reference": "CISA AA20-352A; MITRE ATT&CK T1078.004",
    },
    "T1566.004": {
        "name": "Phishing: Spearphishing Voice",
        "scenarios": ["mgm_resorts"],
        "tactic": "Initial Access",
        "description": (
            "Voice phishing — a phone call posing as a trusted party, using "
            "urgency/social pressure to manipulate a target into helping the attacker."
        ),
        "incident_narrative": (
            "Scattered Spider called MGM's IT help desk, impersonated an employee "
            "found on LinkedIn, and talked the help desk into resetting that "
            "employee's credentials — the entire breach started with a single phone "
            "call, no malware, no exploit."
        ),
        "source_reference": (
            "MITRE ATT&CK T1566.004; Scattered Spider (Mandiant/CrowdStrike/Microsoft "
            "reporting on the 2023 MGM incident)"
        ),
    },
    "T1621": {
        "name": "Multi-Factor Authentication Request Generation",
        "scenarios": ["mgm_resorts"],
        "tactic": "Credential Access",
        "description": (
            "Adversaries with valid credentials but blocked by MFA repeatedly trigger "
            "MFA push notifications hoping the target accepts one (\"MFA fatigue\")."
        ),
        "incident_narrative": (
            "Paired with the vishing call — the attacker used reset access to push "
            "through MFA prompts, completing the account takeover."
        ),
        "source_reference": "MITRE ATT&CK T1621; Scattered Spider MGM 2023 reporting",
    },
    "T1556": {
        "name": "Modify Authentication Process",
        "scenarios": ["mgm_resorts"],
        "tactic": "Credential Access, Defense Evasion, Persistence",
        "description": (
            "Adversaries alter how authentication itself works (MFA registration, "
            "federation trust, auth policy) so access persists even after the initial "
            "credential is rotated."
        ),
        "incident_narrative": (
            "Turned \"we tricked the help desk once\" into durable, hard-to-evict "
            "identity-layer access in the MGM breach."
        ),
        "source_reference": "MITRE ATT&CK T1556; Scattered Spider MGM 2023 reporting",
    },
    "T1491": {
        "name": "Defacement",
        "scenarios": ["mgm_resorts"],
        "tactic": "Impact",
        "description": (
            "Adversaries alter visible content/systems to disrupt operations or send a "
            "message, separate from encryption itself."
        ),
        "incident_narrative": (
            "Casino floor systems, digital signage, and slot machines were knocked "
            "offline or displaying errors in front of live customers — a backend IT "
            "incident turned public, in-person spectacle within hours."
        ),
        "source_reference": "MITRE ATT&CK T1491; MGM 2023 public incident reporting",
    },
    "T1190": {
        "name": "Exploit Public-Facing Application",
        "scenarios": ["log4shell", "nhs_wannacry"],
        "tactic": "Initial Access",
        "description": (
            "Adversaries exploit a weakness in an internet-facing system to gain "
            "initial access without needing credentials."
        ),
        "incident_narrative": (
            "Log4Shell: CVE-2021-44228 let anyone trigger remote code execution via a "
            "single crafted log string, no login needed. NHS WannaCry (nhs-gate-004): "
            "this gate is tagged T1190 for a different reason — it depicts the real "
            "MalwareTech kill-switch domain-registration decision (May 12, 2017), where "
            "defenders had to decide whether to trust unverified threat intelligence "
            "fast enough to open a firewall rule during an active incident. Every "
            "minute of hesitation cost more infected hospital wards — the rare case "
            "where fast action on unverified-but-plausible intelligence was correct."
        ),
        "source_reference": (
            "Log4Shell: CISA/Apache Log4j advisories, MITRE ATT&CK T1190. NHS: NCSC "
            "WannaCry reporting, MalwareTech kill-switch account"
        ),
    },
    "T1059.004": {
        "name": "Command and Scripting Interpreter: Unix Shell",
        "scenarios": ["log4shell"],
        "tactic": "Execution",
        "description": (
            "Using the Unix/Linux shell to execute commands directly — living off the "
            "land on non-Windows infrastructure."
        ),
        "incident_narrative": (
            "Log4j runs everywhere Java runs, including huge swaths of Linux-based "
            "cloud infrastructure, making this a common post-exploitation step."
        ),
        "source_reference": "MITRE ATT&CK T1059.004; Log4Shell CVE-2021-44228 reporting",
    },
    "T1068": {
        "name": "Exploitation for Privilege Escalation",
        "scenarios": ["log4shell"],
        "tactic": "Privilege Escalation",
        "description": (
            "Exploiting a separate vulnerability or design flaw to jump from limited "
            "access to higher privileges."
        ),
        "incident_narrative": (
            "Turned \"code execution as the logging process\" into broader system or "
            "root access following initial Log4Shell exploitation."
        ),
        "source_reference": "MITRE ATT&CK T1068; Log4Shell CVE-2021-44228 reporting",
    },
    "T1105": {
        "name": "Ingress Tool Transfer",
        "scenarios": ["log4shell"],
        "tactic": "Command and Control",
        "description": (
            "Adversaries pull in additional tools/malware/payloads from an external "
            "server onto the compromised system."
        ),
        "incident_narrative": (
            "Log4Shell's initial exploit is small; deploying a cryptominer, backdoor, "
            "or ransomware requires fetching tools in afterward — the moment network "
            "monitoring has its best shot at catching the intrusion."
        ),
        "source_reference": "MITRE ATT&CK T1105; Log4Shell CVE-2021-44228 reporting",
    },
    "T1210": {
        "name": "Exploitation of Remote Services",
        "scenarios": ["log4shell"],
        "tactic": "Lateral Movement",
        "description": (
            "Exploiting a vulnerability in a network-reachable service to gain access "
            "or execute code remotely."
        ),
        "incident_narrative": (
            "The broader category Log4Shell belongs to — the vulnerability lived "
            "inside a logging library, reachable through almost any application that "
            "logged user-controlled input, not just a public-facing login page."
        ),
        "source_reference": "MITRE ATT&CK T1210; Log4Shell CVE-2021-44228 reporting",
    },
    "T1021.002": {
        "name": "Remote Services: SMB/Windows Admin Shares",
        "scenarios": ["nhs_wannacry"],
        "tactic": "Lateral Movement",
        "description": (
            "Adversaries use Windows' built-in hidden network shares (C$, ADMIN$, "
            "IPC$) to move between systems and run code as the logged-in user."
        ),
        "incident_narrative": (
            "WannaCry exploited a flaw in the SMB protocol itself (EternalBlue, "
            "CVE-2017-0144) for unauthenticated code execution, spreading "
            "automatically to any unpatched machine with zero credentials and zero "
            "human interaction."
        ),
        "source_reference": "NCSC WannaCry reporting; MITRE ATT&CK T1021.002",
    },
    "T1570": {
        "name": "Lateral Tool Transfer",
        "scenarios": ["nhs_wannacry"],
        "tactic": "Lateral Movement",
        "description": (
            "Adversaries copy tools and payloads across to other systems in the "
            "environment — the mechanical \"spreading\" step."
        ),
        "incident_narrative": (
            "Why WannaCry was a worm and not just ransomware — each newly infected "
            "machine immediately began scanning for and infecting the next one, "
            "crossing from a single NHS trust to over a third of NHS England's "
            "hospital trusts within hours."
        ),
        "source_reference": "NCSC WannaCry reporting; MITRE ATT&CK T1570",
    },
    "T1485": {
        "name": "Data Destruction",
        "scenarios": ["nhs_wannacry"],
        "tactic": "Impact",
        "description": (
            "Adversaries destroy data outright (overwrite, delete, corrupt) rather "
            "than merely encrypting it for ransom."
        ),
        "incident_narrative": (
            "Analysis of WannaCry's payment mechanism showed it couldn't actually "
            "track which victim had paid, meaning even a paying victim had no real "
            "path to recovery — closer to a destructive worm wearing a ransomware "
            "mask than functioning ransomware."
        ),
        "source_reference": "NCSC WannaCry reporting; MITRE ATT&CK T1485",
    },
}
