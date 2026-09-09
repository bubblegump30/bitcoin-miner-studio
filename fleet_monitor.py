import csv
import json
import time
from collections import deque
from pathlib import Path


class FleetMonitor:
    def __init__(self, max_samples=180, storage_path=None):
        self.max_samples = int(max_samples)
        self.history = {}
        self.baseline_hashrate = {}
        self.offline_since = {}
        self.acknowledged_alerts = set()
        self.events = deque(maxlen=500)
        self.storage_path = Path(storage_path) if storage_path else None

        if self.storage_path:
            self.load()

    def _alert_key(self, ip, kind):
        return f"{ip}|{kind}"

    def _event(self, ip, kind, message, severity="info"):
        item = {
            "ts": time.time(),
            "ip": str(ip),
            "kind": str(kind),
            "message": str(message),
            "severity": str(severity),
        }
        self.events.appendleft(item)

    def recent_events(self, limit=100):
        return list(self.events)[:max(1, int(limit))]

    def acknowledge(self, ip, kind):
        ip = str(ip)
        kind = str(kind)
        self.acknowledged_alerts.add(self._alert_key(ip, kind))
        self._event(ip, "acknowledged", f"Acknowledged {kind} alert.", "info")
        self.save()

    def acknowledge_all(self, ip):
        ip = str(ip)
        for kind in ("offline", "temperature", "hashrate"):
            self.acknowledged_alerts.add(self._alert_key(ip, kind))
        self._event(ip, "acknowledged", "Acknowledged active alerts.", "info")
        self.save()

    def clear_acknowledgements_for_recovered(self, device):
        ip = str(device.get("ip", ""))
        if not ip:
            return

        active_kinds = {a["kind"] for a in self.alerts(device, include_acknowledged=True)}
        to_remove = []
        for key in self.acknowledged_alerts:
            if not key.startswith(ip + "|"):
                continue
            kind = key.split("|", 1)[1]
            if kind not in active_kinds:
                to_remove.append(key)
        for key in to_remove:
            self.acknowledged_alerts.discard(key)

    def record(self, device):
        ip = str(device.get("ip", ""))
        if not ip:
            return

        now = time.time()
        status = str(device.get("status", "Unknown"))
        previous_rows = self.history.get(ip)
        previous_status = previous_rows[-1]["status"] if previous_rows else None

        row = {
            "ts": now,
            "status": status,
            "hashrate_hs": float(device.get("hashrate_hs", 0) or 0),
            "temperature_c": device.get("temperature_c"),
            "fan_rpm": device.get("fan_rpm"),
            "power_w": device.get("power_w"),
            "accepted": int(device.get("accepted", 0) or 0),
            "rejected": int(device.get("rejected", 0) or 0),
            "hardware_errors": int(device.get("hardware_errors", 0) or 0),
        }

        q = self.history.setdefault(ip, deque(maxlen=self.max_samples))
        q.append(row)

        if status == "Offline":
            if ip not in self.offline_since:
                self.offline_since[ip] = now
                self._event(ip, "offline", f"{ip} went offline.", "critical")
        else:
            if ip in self.offline_since:
                duration = max(0.0, now - self.offline_since[ip])
                self._event(ip, "recovered", f"{ip} recovered after {int(duration)} seconds.", "info")
            self.offline_since.pop(ip, None)

        if previous_status is not None and previous_status != status and status != "Offline":
            self._event(ip, "status", f"Status changed: {previous_status} → {status}.", "info")

        if status == "Online" and row["hashrate_hs"] > 0:
            current = row["hashrate_hs"]
            baseline = self.baseline_hashrate.get(ip)
            if not baseline:
                self.baseline_hashrate[ip] = current
            else:
                # Slow-moving baseline: resistant to individual noisy samples.
                self.baseline_hashrate[ip] = baseline * 0.90 + current * 0.10

        self.clear_acknowledgements_for_recovered(device)
        self.save()

    def recent(self, ip):
        return list(self.history.get(str(ip), []))

    def availability_percent(self, ip):
        rows = self.recent(ip)
        if not rows:
            return None
        online = sum(1 for r in rows if r.get("status") in ("Online", "Web UI only"))
        return online / len(rows) * 100.0

    def offline_duration_seconds(self, ip, now=None):
        started = self.offline_since.get(str(ip))
        if not started:
            return 0.0
        now = time.time() if now is None else float(now)
        return max(0.0, now - float(started))

    def health_score(self, device, temp_limit=80.0, drop_percent=25.0):
        """
        Best-effort 0-100 operational score.

        The score is intentionally transparent rather than predictive:
        - reachability/status
        - temperature headroom
        - current hashrate vs learned baseline
        - hardware error pressure
        """
        status = str(device.get("status", "Unknown"))
        if status == "Offline":
            return 0
        if status in ("Unknown", "Candidate"):
            return 35
        if status == "Web UI only":
            return 55

        score = 100.0

        temp = device.get("temperature_c")
        if temp is not None:
            temp = float(temp)
            if temp >= temp_limit:
                score -= min(35.0, 15.0 + (temp - temp_limit) * 2.0)
            elif temp >= temp_limit - 10:
                score -= (temp - (temp_limit - 10)) * 1.2

        ip = str(device.get("ip", ""))
        current = float(device.get("hashrate_hs", 0) or 0)
        baseline = float(self.baseline_hashrate.get(ip, 0) or 0)
        if current <= 0:
            score -= 35.0
        elif baseline > 0:
            ratio = current / baseline
            if ratio < 1.0:
                score -= min(35.0, (1.0 - ratio) * 55.0)

        hw = int(device.get("hardware_errors", 0) or 0)
        accepted = int(device.get("accepted", 0) or 0)
        if hw > 0:
            denominator = max(1, accepted + hw)
            hw_ratio = hw / denominator
            score -= min(20.0, hw_ratio * 100.0)

        return max(0, min(100, int(round(score))))

    def health_explanation(self, device, temp_limit=80.0, drop_percent=25.0):
        score = self.health_score(device, temp_limit=temp_limit, drop_percent=drop_percent)
        parts = []

        status = str(device.get("status", "Unknown"))
        parts.append(f"Status: {status}")

        temp = device.get("temperature_c")
        if temp is None:
            parts.append("Temperature: unavailable")
        else:
            parts.append(f"Temperature: {float(temp):.1f} °C")

        ip = str(device.get("ip", ""))
        current = float(device.get("hashrate_hs", 0) or 0)
        baseline = float(self.baseline_hashrate.get(ip, 0) or 0)
        if baseline > 0:
            ratio = current / baseline if baseline else 0
            parts.append(f"Hashrate vs baseline: {ratio*100:.1f}%")
        else:
            parts.append("Hashrate baseline: learning")

        hw = int(device.get("hardware_errors", 0) or 0)
        parts.append(f"Hardware errors: {hw}")

        return {
            "score": score,
            "summary": " • ".join(parts),
        }

    def alerts(self, device, temp_limit=80.0, drop_percent=25.0, include_acknowledged=False):
        alerts = []
        ip = str(device.get("ip", ""))

        status = str(device.get("status", "Unknown"))
        if status == "Offline":
            alerts.append({
                "severity": "critical",
                "kind": "offline",
                "message": f"{ip} is offline.",
            })

        temp = device.get("temperature_c")
        if temp is not None and float(temp) >= float(temp_limit):
            alerts.append({
                "severity": "critical",
                "kind": "temperature",
                "message": f"{ip} temperature is {float(temp):.1f} °C.",
            })

        current = float(device.get("hashrate_hs", 0) or 0)
        baseline = float(self.baseline_hashrate.get(ip, 0) or 0)
        if current > 0 and baseline > 0 and drop_percent > 0:
            threshold = baseline * (1.0 - float(drop_percent) / 100.0)
            if current < threshold:
                drop = (1.0 - current / baseline) * 100.0
                alerts.append({
                    "severity": "warning",
                    "kind": "hashrate",
                    "message": f"{ip} hashrate is {drop:.1f}% below its learned baseline.",
                })

        if include_acknowledged:
            return alerts

        return [
            alert for alert in alerts
            if self._alert_key(ip, alert["kind"]) not in self.acknowledged_alerts
        ]

    def save(self):
        if not self.storage_path:
            return

        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "max_samples": self.max_samples,
            "history": {
                ip: list(rows)
                for ip, rows in self.history.items()
            },
            "baseline_hashrate": self.baseline_hashrate,
            "offline_since": self.offline_since,
            "acknowledged_alerts": sorted(self.acknowledged_alerts),
            "events": list(self.events),
        }

        temp = self.storage_path.with_suffix(self.storage_path.suffix + ".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(self.storage_path)

    def load(self):
        if not self.storage_path or not self.storage_path.exists():
            return

        try:
            payload = json.loads(self.storage_path.read_text(encoding="utf-8"))
        except Exception:
            return

        self.history = {}
        for ip, rows in (payload.get("history") or {}).items():
            q = deque(maxlen=self.max_samples)
            for row in rows[-self.max_samples:]:
                if isinstance(row, dict):
                    q.append(row)
            self.history[str(ip)] = q

        self.baseline_hashrate = {
            str(k): float(v)
            for k, v in (payload.get("baseline_hashrate") or {}).items()
            if isinstance(v, (int, float))
        }

        self.offline_since = {
            str(k): float(v)
            for k, v in (payload.get("offline_since") or {}).items()
            if isinstance(v, (int, float))
        }

        self.acknowledged_alerts = set(
            str(x) for x in (payload.get("acknowledged_alerts") or [])
        )

        self.events = deque(maxlen=500)
        for item in (payload.get("events") or [])[:500]:
            if isinstance(item, dict):
                self.events.append(item)


def export_fleet_json(path, devices, monitor, aliases=None, groups=None):
    aliases = aliases or {}
    groups = groups or {}
    payload = {
        "exported_at": time.time(),
        "devices": [],
    }

    for ip, device in sorted(devices.items()):
        payload["devices"].append({
            "alias": aliases.get(ip, ""),
            "group": groups.get(ip, ""),
            "device": device,
            "availability_percent": monitor.availability_percent(ip),
            "offline_duration_seconds": monitor.offline_duration_seconds(ip),
            "health_score": monitor.health_score(device),
            "history": monitor.recent(ip),
        })

    Path(path).write_text(json.dumps(payload, indent=2), encoding="utf-8")


def export_fleet_csv(path, devices, monitor, aliases=None, groups=None):
    aliases = aliases or {}
    groups = groups or {}

    fieldnames = [
        "ip", "alias", "group", "model", "verification", "status",
        "health_score", "hashrate_hs", "temperature_c", "fan_rpm", "power_w",
        "efficiency_j_th", "uptime_s", "pool_url", "pool_user",
        "latency_ms", "availability_percent", "offline_duration_seconds",
    ]

    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for ip, d in sorted(devices.items()):
            writer.writerow({
                "ip": ip,
                "alias": aliases.get(ip, ""),
                "group": groups.get(ip, ""),
                "model": d.get("model", ""),
                "verification": d.get("verification", ""),
                "status": d.get("status", ""),
                "health_score": monitor.health_score(d),
                "hashrate_hs": d.get("hashrate_hs", 0),
                "temperature_c": d.get("temperature_c"),
                "fan_rpm": d.get("fan_rpm"),
                "power_w": d.get("power_w"),
                "efficiency_j_th": d.get("efficiency_j_th"),
                "uptime_s": d.get("uptime_s", 0),
                "pool_url": d.get("pool_url", ""),
                "pool_user": d.get("pool_user", ""),
                "latency_ms": d.get("latency_ms"),
                "availability_percent": monitor.availability_percent(ip),
                "offline_duration_seconds": monitor.offline_duration_seconds(ip),
            })
