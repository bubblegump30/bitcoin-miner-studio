"""Bitcoin Miner Studio v1.3.0.1 — Hardware Compatibility Center hotfix.

This module is read-only and local. It classifies the ASIC evidence already
collected by Bitcoin Miner Studio. It does not scan the LAN, log into devices,
change pools, restart miners, flash firmware, or make network requests.

"Verified Runtime" means Miner Studio positively verified ASIC-specific runtime
evidence. It is not a manufacturer certification.
"""
from __future__ import annotations

import copy
import time


FAMILY_CATALOG = [
    {
        "id": "bitmain-antminer",
        "vendor": "Bitmain",
        "family": "Antminer",
        "match_terms": ("bitmain", "antminer"),
        "examples": ["S19 family", "S21 family", "T21 family"],
        "recognition": "cgminer-compatible API or recognized Antminer/Bitmain Web UI",
        "notes": "Full controls require a verified API response; Web-UI recognition alone remains monitoring/navigation limited.",
    },
    {
        "id": "microbt-whatsminer",
        "vendor": "MicroBT",
        "family": "WhatsMiner",
        "match_terms": ("microbt", "whatsminer", "whats miner"),
        "examples": ["M30 family", "M50 family", "M60 family"],
        "recognition": "cgminer-compatible API or recognized WhatsMiner/MicroBT Web UI",
        "notes": "Firmware/API behavior varies. Miner Studio only enables controls actually verified at runtime.",
    },
    {
        "id": "canaan-avalon",
        "vendor": "Canaan",
        "family": "Avalon",
        "match_terms": ("canaan", "avalon", "avalonminer"),
        "examples": ["Avalon A12 family", "Avalon A13 family", "Avalon A14/A15 family"],
        "recognition": "cgminer-compatible API or recognized Avalon/Canaan Web UI",
        "notes": "Runtime telemetry/control availability depends on the firmware/API response exposed by the miner.",
    },
    {
        "id": "generic-cgminer",
        "vendor": "Generic",
        "family": "cgminer-compatible ASIC",
        "match_terms": ("cgminer-compatible", "cgminer compatible"),
        "examples": ["Vendor/model not identified"],
        "recognition": "verified cgminer-compatible ASIC API response",
        "notes": "Generic API support is intentionally conservative. Model-specific compatibility is not assumed.",
    },
]


def _norm(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def catalog_for_ui():
    """Return a presentation-safe copy of the built-in local family registry."""
    rows = []
    for item in FAMILY_CATALOG:
        row = copy.deepcopy(item)
        row.pop("match_terms", None)

        # pywebview's bridge should receive a JSON-style array here. Keep this
        # defensive even if a future catalog entry is accidentally authored as
        # a tuple or a single string.
        examples = row.get("examples", [])
        if isinstance(examples, str):
            examples = [examples]
        elif not isinstance(examples, list):
            examples = list(examples or [])
        row["examples"] = [str(value) for value in examples]

        row["capability_policy"] = {
            "monitoring": "Available when ASIC-specific runtime evidence is verified.",
            "web_ui": "Available when the ASIC Web UI is positively recognized.",
            "pool_control": "Enabled only when API + pool retrieval are verified.",
            "restart": "Enabled only when the ASIC API is verified.",
            "solo_bridge": "Eligible only for API-verified ASICs and the existing private-LAN authorization flow.",
        }
        rows.append(row)
    return rows


def match_family(device):
    device = dict(device or {})
    haystack = " ".join(
        _norm(device.get(key))
        for key in ("vendor", "model", "firmware", "web_server", "web_realm", "verification")
    )
    for item in FAMILY_CATALOG:
        if any(term in haystack for term in item["match_terms"]):
            return item
    return None


def _evidence(device):
    evidence = []
    if device.get("api_verified"):
        evidence.append("ASIC API verified")
    if device.get("recognized_web_asic"):
        evidence.append("Recognized ASIC Web UI")
    if device.get("web_available") and not device.get("recognized_web_asic"):
        evidence.append("Generic Web UI only")
    if device.get("https_available"):
        evidence.append("HTTPS reachable")
    elif device.get("http_available"):
        evidence.append("HTTP reachable")
    if not evidence:
        evidence.append("No positive ASIC evidence")
    return evidence


def classify_device(device):
    """Classify an existing fleet record without probing the device."""
    d = dict(device or {})
    api_verified = bool(d.get("api_verified"))
    recognized_web = bool(d.get("recognized_web_asic"))
    confirmed = bool(api_verified or recognized_web)
    family = match_family(d) if confirmed else None

    if not confirmed:
        level = "NOT PROMOTED"
        status_key = "not_promoted"
        confidence = 0
        explanation = (
            "No positive ASIC-specific evidence is present. An open management page "
            "or TCP port alone is not enough to classify this device as an ASIC."
        )
    elif api_verified and family and family["id"] != "generic-cgminer":
        level = "VERIFIED RUNTIME"
        status_key = "verified"
        confidence = 100
        explanation = (
            "ASIC API evidence is verified and the device matches a recognized Miner Studio family. "
            "This is runtime verification, not manufacturer certification."
        )
    elif recognized_web and family and family["id"] != "generic-cgminer":
        level = "SUPPORTED FAMILY"
        status_key = "family"
        confidence = 85
        explanation = (
            "The Web UI matches a recognized ASIC family, but the management API is not verified. "
            "Privileged controls remain disabled unless runtime API evidence is obtained."
        )
    elif api_verified:
        level = "GENERIC API"
        status_key = "limited"
        confidence = 90
        explanation = (
            "A cgminer-compatible ASIC API was verified, but Miner Studio cannot confidently "
            "map the device to a specific supported vendor/model family."
        )
    else:
        level = "LIMITED"
        status_key = "limited"
        confidence = 70
        explanation = "ASIC evidence exists, but model/family capability mapping is limited."

    capabilities = {
        "monitoring": bool(api_verified),
        "web_ui": bool(d.get("can_open_web") or recognized_web),
        "pool_control": bool(api_verified and d.get("can_switch_pool")),
        "restart": bool(api_verified and d.get("can_restart")),
        "solo_bridge": bool(api_verified),
    }
    full_control = bool(
        capabilities["monitoring"]
        and capabilities["pool_control"]
        and capabilities["restart"]
        and capabilities["solo_bridge"]
    )

    telemetry = {
        "hashrate": d.get("hashrate_hs") not in (None, 0, 0.0),
        "temperature": d.get("temperature_c") is not None,
        "fan": d.get("fan_rpm") is not None,
        "power": d.get("power_w") is not None,
        "efficiency": d.get("efficiency_j_th") is not None,
    }

    return {
        "ip": str(d.get("ip") or ""),
        "alias": str(d.get("alias") or ""),
        "group": str(d.get("group") or ""),
        "vendor": str(d.get("vendor") or "Unknown"),
        "model": str(d.get("model") or "Unknown device"),
        "firmware": str(d.get("firmware") or ""),
        "verification": str(d.get("verification") or "UNVERIFIED"),
        "status": str(d.get("status") or "Offline"),
        "compatibility_level": level,
        "status_key": status_key,
        "confidence": confidence,
        "confirmed_asic": confirmed,
        "family_id": family["id"] if family else "",
        "family": family["family"] if family else "Unknown",
        "family_vendor": family["vendor"] if family else "",
        "evidence": _evidence(d),
        "explanation": explanation,
        "capabilities": capabilities,
        "full_control": full_control,
        "telemetry": telemetry,
        "health": d.get("health"),
        "availability": d.get("availability"),
        "hashrate_hs": float(d.get("hashrate_hs") or 0),
        "temperature_c": d.get("temperature_c"),
        "power_w": d.get("power_w"),
        "efficiency_j_th": d.get("efficiency_j_th"),
    }


def compatibility_snapshot(devices=None, known_devices=None):
    devices = [dict(x or {}) for x in (devices or [])]
    known_devices = list(known_devices or [])
    rows = [classify_device(d) for d in devices]

    summary = {
        "fleet_records": len(rows),
        "confirmed_asics": sum(1 for x in rows if x["confirmed_asic"]),
        "verified_runtime": sum(1 for x in rows if x["status_key"] == "verified"),
        "supported_family": sum(1 for x in rows if x["status_key"] == "family"),
        "generic_or_limited": sum(1 for x in rows if x["status_key"] == "limited"),
        "not_promoted": sum(1 for x in rows if x["status_key"] == "not_promoted"),
        "full_control": sum(1 for x in rows if x["full_control"]),
        "monitoring": sum(1 for x in rows if x["capabilities"]["monitoring"]),
        "known_addresses": len(known_devices),
    }

    return {
        "schema": 1,
        "summary": summary,
        "devices": rows,
        "families": catalog_for_ui(),
        "policy": {
            "positive_evidence_only": True,
            "generic_http_is_not_asic": True,
            "open_4028_is_not_asic": True,
            "manufacturer_certification": False,
            "automatic_firmware_changes": False,
            "cloud_database": False,
        },
        "legend": [
            {
                "key": "verified",
                "label": "VERIFIED RUNTIME",
                "detail": "Positive ASIC API evidence + recognized family. Not manufacturer certification.",
            },
            {
                "key": "family",
                "label": "SUPPORTED FAMILY",
                "detail": "Recognized ASIC-family Web UI; privileged API controls remain gated.",
            },
            {
                "key": "limited",
                "label": "GENERIC / LIMITED",
                "detail": "ASIC-specific evidence exists, but model-family coverage or controls are limited.",
            },
            {
                "key": "not_promoted",
                "label": "NOT PROMOTED",
                "detail": "No positive ASIC evidence; Miner Studio refuses to guess.",
            },
        ],
    }


def sanitized_report(snapshot):
    """Create a privacy-safe report suitable for a public GitHub/support issue."""
    snapshot = dict(snapshot or {})
    devices = []
    for index, row in enumerate(snapshot.get("devices") or [], 1):
        row = dict(row or {})
        devices.append({
            "device": f"private-device-{index}",
            "vendor": row.get("vendor"),
            "model": row.get("model"),
            "firmware": row.get("firmware"),
            "verification": row.get("verification"),
            "compatibility_level": row.get("compatibility_level"),
            "family": row.get("family"),
            "evidence": list(row.get("evidence") or []),
            "capabilities": dict(row.get("capabilities") or {}),
            "telemetry_fields_available": [
                key for key, present in dict(row.get("telemetry") or {}).items() if present
            ],
        })

    return {
        "schema": 1,
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "summary": dict(snapshot.get("summary") or {}),
        "devices": devices,
        "families": list(snapshot.get("families") or []),
        "policy": dict(snapshot.get("policy") or {}),
        "privacy": {
            "private_ip_addresses": "excluded",
            "pool_urls": "excluded",
            "pool_workers": "excluded",
            "credentials": "excluded",
            "device_notes": "excluded",
        },
    }
