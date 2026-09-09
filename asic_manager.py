import concurrent.futures
import ipaddress
import json
import re
import socket
import time
import urllib.error
import urllib.request


CGMINER_PORT = 4028


def default_private_cidr():
    """Return a conservative /24 derived from the machine's active private IPv4."""
    candidates = []

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            candidates.append(s.getsockname()[0])
        finally:
            s.close()
    except Exception:
        pass

    try:
        _, _, addrs = socket.gethostbyname_ex(socket.gethostname())
        candidates.extend(addrs)
    except Exception:
        pass

    for value in candidates:
        try:
            ip = ipaddress.ip_address(value)
        except ValueError:
            continue
        if isinstance(ip, ipaddress.IPv4Address) and ip.is_private and not ip.is_loopback:
            return str(ipaddress.ip_network(f"{ip}/24", strict=False))

    return "192.168.1.0/24"


def ensure_private_host(host):
    try:
        ip = ipaddress.ip_address(host)
    except ValueError as exc:
        raise ValueError("ASIC address must be a literal private/local IPv4 address.") from exc

    if not isinstance(ip, ipaddress.IPv4Address):
        raise ValueError("Only IPv4 ASIC addresses are supported in v0.3.0.")

    if not (ip.is_private or ip.is_loopback or ip.is_link_local):
        raise ValueError("ASIC Control Center is restricted to private/local IP addresses.")
    return str(ip)


def validate_scan_network(cidr):
    try:
        network = ipaddress.ip_network(str(cidr).strip(), strict=False)
    except ValueError as exc:
        raise ValueError("Enter a valid private IPv4 CIDR, for example 192.168.1.0/24.") from exc

    if not isinstance(network, ipaddress.IPv4Network):
        raise ValueError("Only IPv4 discovery is supported in v0.3.0.")
    if not (network.is_private or network.network_address.is_loopback or network.network_address.is_link_local):
        raise ValueError("Discovery is restricted to private/local networks.")
    if network.num_addresses > 256:
        raise ValueError("For safety and responsiveness, discovery is limited to /24 or smaller ranges.")
    return network


def probe_ports(ip, timeout=0.18):
    result = {"ip": ip, "cgminer": False, "http": False, "https": False}
    for port, key in ((4028, "cgminer"), (80, "http"), (443, "https")):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        try:
            result[key] = sock.connect_ex((ip, port)) == 0
        except Exception:
            result[key] = False
        finally:
            sock.close()
    return result


def discover_devices(cidr, timeout=0.18, max_workers=64, progress_callback=None):
    network = validate_scan_network(cidr)
    hosts = [str(ip) for ip in network.hosts()]
    found = []

    if not hosts and network.num_addresses == 1:
        hosts = [str(network.network_address)]

    checked = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {
            pool.submit(probe_ports, ip, timeout): ip
            for ip in hosts
        }
        for future in concurrent.futures.as_completed(future_map):
            checked += 1
            try:
                item = future.result()
            except Exception:
                item = None
            if item and any(item[k] for k in ("cgminer", "http", "https")):
                found.append(item)
            if progress_callback:
                try:
                    progress_callback(checked, len(hosts))
                except Exception:
                    pass

    found.sort(key=lambda d: tuple(int(x) for x in d["ip"].split(".")))
    return found


def cgminer_command(ip, command, parameter=None, timeout=2.0):
    ip = ensure_private_host(ip)
    request = {"command": str(command)}
    if parameter is not None:
        request["parameter"] = str(parameter)

    raw_request = (json.dumps(request, separators=(",", ":")) + "\0").encode("utf-8")

    sock = socket.create_connection((ip, CGMINER_PORT), timeout=timeout)
    sock.settimeout(timeout)
    chunks = []
    try:
        sock.sendall(raw_request)
        while True:
            try:
                chunk = sock.recv(65536)
            except socket.timeout:
                break
            if not chunk:
                break
            chunks.append(chunk)
            if b"\0" in chunk:
                break
            if sum(len(c) for c in chunks) > 4_000_000:
                break
    finally:
        try:
            sock.close()
        except Exception:
            pass

    raw = b"".join(chunks).split(b"\0", 1)[0].decode("utf-8", errors="replace").strip()
    if not raw:
        raise RuntimeError(f"No response from cgminer API at {ip}:4028.")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return parse_legacy_response(raw)


def parse_legacy_response(raw):
    sections = {}
    for block in raw.split("|"):
        block = block.strip()
        if not block:
            continue
        fields = {}
        section_name = "DATA"
        for i, token in enumerate(block.split(",")):
            token = token.strip()
            if not token:
                continue
            if "=" in token:
                key, value = token.split("=", 1)
                key = key.strip()
                value = value.strip()
                if i == 0 and key.isupper():
                    section_name = key
                    fields[key] = value
                else:
                    fields[key] = value
            elif i == 0:
                section_name = token
        sections.setdefault(section_name, []).append(fields)
    return sections


def _section(response, name):
    if not isinstance(response, dict):
        return []
    value = response.get(name)
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if isinstance(value, dict):
        return [value]
    return []


def _first_number(mapping, keys):
    for key in keys:
        if key in mapping:
            value = mapping.get(key)
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                m = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
                if m:
                    try:
                        return float(m.group(0))
                    except ValueError:
                        pass
    return None


def _hashrate_hs(summary):
    variants = [
        ("THS 5s", 1e12),
        ("THS av", 1e12),
        ("GHS 5s", 1e9),
        ("GHS av", 1e9),
        ("MHS 5s", 1e6),
        ("MHS av", 1e6),
        ("KHS 5s", 1e3),
        ("KHS av", 1e3),
        ("HS 5s", 1.0),
        ("HS av", 1.0),
    ]
    for key, mul in variants:
        if key in summary:
            value = _first_number(summary, [key])
            if value is not None:
                return max(0.0, value * mul)

    # Common vendor variants.
    for key in ("rate_5s", "rate_avg", "hashrate", "Hashrate"):
        value = _first_number(summary, [key])
        if value is not None:
            # Most bmminer rate_* values are GH/s. Keep this best-effort.
            return max(0.0, value * 1e9)
    return 0.0


def _flatten_dicts(response):
    items = []
    if not isinstance(response, dict):
        return items
    for value in response.values():
        if isinstance(value, list):
            items.extend([x for x in value if isinstance(x, dict)])
        elif isinstance(value, dict):
            items.append(value)
    return items


def _extract_temperature(stats_response):
    values = []
    for row in _flatten_dicts(stats_response):
        for key, value in row.items():
            if "temp" not in str(key).lower():
                continue
            if isinstance(value, (int, float)):
                candidates = [float(value)]
            else:
                candidates = []
                for m in re.findall(r"-?\d+(?:\.\d+)?", str(value)):
                    try:
                        candidates.append(float(m))
                    except ValueError:
                        pass
            values.extend(x for x in candidates if 0 < x < 130)
    return max(values) if values else None


def _extract_fan(stats_response):
    values = []
    for row in _flatten_dicts(stats_response):
        for key, value in row.items():
            if "fan" not in str(key).lower():
                continue
            num = _first_number({key: value}, [key])
            if num is not None and 100 <= num <= 20000:
                values.append(num)
    return max(values) if values else None


def _extract_power(stats_response):
    values = []
    for row in _flatten_dicts(stats_response):
        for key, value in row.items():
            k = str(key).lower()
            if "power" not in k and "watt" not in k:
                continue
            num = _first_number({key: value}, [key])
            if num is not None and 1 <= num <= 100000:
                values.append(num)
    return max(values) if values else None


def _extract_model(stats_response):
    for row in _flatten_dicts(stats_response):
        for key in ("Type", "type", "Model", "model", "Miner", "miner", "Device"):
            value = row.get(key)
            if value:
                return str(value)[:80]
    return "cgminer-compatible ASIC"


def _extract_pool(pools_response):
    pools = _section(pools_response, "POOLS")
    if not pools:
        pools = _section(pools_response, "POOL")
    if not pools:
        return "", "", []

    selected = None
    for pool in pools:
        active = str(pool.get("Stratum Active", "")).lower()
        if active in ("true", "yes", "1"):
            selected = pool
            break
    if selected is None:
        selected = pools[0]

    return (
        str(selected.get("URL", selected.get("Stratum URL", ""))),
        str(selected.get("User", "")),
        pools,
    )


def http_identity(ip, timeout=1.0):
    ip = ensure_private_host(ip)
    for scheme in ("http", "https"):
        try:
            req = urllib.request.Request(
                f"{scheme}://{ip}/",
                method="HEAD",
                headers={"User-Agent": "BitcoinMinerStudio/0.5.0.1"},
            )
            context = None
            if scheme == "https":
                import ssl
                context = ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=context) as resp:
                return {
                    "scheme": scheme,
                    "server": resp.headers.get("Server", ""),
                    "realm": resp.headers.get("WWW-Authenticate", ""),
                    "status": getattr(resp, "status", 200),
                }
        except urllib.error.HTTPError as exc:
            # 401/403 still prove a Web UI exists and often contain the ASIC
            # model/vendor in Server or WWW-Authenticate headers.
            return {
                "scheme": scheme,
                "server": exc.headers.get("Server", ""),
                "realm": exc.headers.get("WWW-Authenticate", ""),
                "status": int(getattr(exc, "code", 0) or 0),
            }
        except Exception:
            continue
    return {}


def query_device(ip, timeout=2.0):
    ip = ensure_private_host(ip)
    started = time.perf_counter()

    summary_response = None
    stats_response = {}
    pools_response = {}
    api_error = ""
    api_verified = False

    try:
        summary_response = cgminer_command(ip, "summary", timeout=timeout)
        summary_rows = _section(summary_response or {}, "SUMMARY")
        if not summary_rows:
            summary_rows = _section(summary_response or {}, "Summary")
        api_verified = bool(summary_rows)

        if api_verified:
            try:
                stats_response = cgminer_command(ip, "stats", timeout=timeout)
            except Exception:
                stats_response = {}
            try:
                pools_response = cgminer_command(ip, "pools", timeout=timeout)
            except Exception:
                pools_response = {}
    except Exception as exc:
        api_error = str(exc)

    identity = http_identity(ip, timeout=min(1.0, timeout))
    latency_ms = (time.perf_counter() - started) * 1000.0

    summary_rows = _section(summary_response or {}, "SUMMARY")
    if not summary_rows:
        summary_rows = _section(summary_response or {}, "Summary")
    summary = summary_rows[0] if summary_rows else {}

    web_available = bool(identity)
    http_available = identity.get("scheme") == "http"
    https_available = identity.get("scheme") == "https"

    pool_url, pool_user, pools = _extract_pool(pools_response)
    pools_verified = bool(pools)

    model = "Unknown network device"
    vendor = ""
    firmware = ""
    recognized_web_asic = False

    if api_verified:
        model = _extract_model(stats_response)
        vendor = "cgminer-compatible"
    elif web_available:
        server = identity.get("server", "")
        realm = identity.get("realm", "")
        identity_text = f"{server} {realm}".lower()

        if "antminer" in identity_text or "bitmain" in identity_text:
            model = "Antminer (Web UI)"
            vendor = "Bitmain / Antminer"
            recognized_web_asic = True
        elif "whatsminer" in identity_text or "microbt" in identity_text:
            model = "WhatsMiner (Web UI)"
            vendor = "MicroBT / WhatsMiner"
            recognized_web_asic = True
        elif "avalon" in identity_text or "canaan" in identity_text:
            model = "AvalonMiner (Web UI)"
            vendor = "Canaan / Avalon"
            recognized_web_asic = True
        else:
            # Routers, NAS boxes, printers, PCs, consoles and many other LAN
            # devices expose HTTP/HTTPS management endpoints. A Web UI alone
            # is not ASIC-specific evidence.
            model = "Unknown network device"

    if api_verified and model == "cgminer-compatible ASIC":
        identity_text = f"{identity.get('server', '')} {identity.get('realm', '')}".lower()
        if "antminer" in identity_text or "bitmain" in identity_text:
            model = "Antminer"
            vendor = "Bitmain / Antminer"

    hashrate = _hashrate_hs(summary) if api_verified else 0.0
    elapsed = _first_number(summary, ["Elapsed", "elapsed", "Uptime", "uptime"]) or 0.0
    accepted = int(_first_number(summary, ["Accepted", "accepted"]) or 0)
    rejected = int(_first_number(summary, ["Rejected", "rejected"]) or 0)
    hw_errors = int(_first_number(summary, ["Hardware Errors", "Hardware Errors%", "HW", "hw"]) or 0)
    temp = _extract_temperature(stats_response) if api_verified else None
    fan = _extract_fan(stats_response) if api_verified else None
    power = _extract_power(stats_response) if api_verified else None

    efficiency = None
    if power and hashrate > 0:
        ths = hashrate / 1e12
        if ths > 0:
            efficiency = power / ths

    # Verification state is intentionally conservative.
    if api_verified:
        verification = "VERIFIED ASIC"
        status = "Online"
    elif recognized_web_asic:
        verification = "RECOGNIZED ASIC WEB UI"
        status = "Web UI only"
    else:
        verification = "UNVERIFIED"
        status = "Offline"

    # Privileged actions are not considered available merely because 4028 was open.
    # v0.3.1 only enables pool switching if pools were actually retrieved.
    # Restart requires a verified API and is still subject to firmware rejection.
    can_open_web = bool(api_verified or recognized_web_asic)
    can_switch_pool = api_verified and pools_verified
    can_restart = api_verified

    return {
        "ip": ip,
        "model": model,
        "vendor": vendor,
        "firmware": firmware,
        "verification": verification,
        "status": status,
        "api_verified": api_verified,
        "recognized_web_asic": recognized_web_asic,
        "web_available": web_available,
        "http_available": http_available,
        "https_available": https_available,
        "can_open_web": can_open_web,
        "can_switch_pool": can_switch_pool,
        "can_restart": can_restart,
        "hashrate_hs": hashrate,
        "temperature_c": temp,
        "fan_rpm": fan,
        "power_w": power,
        "efficiency_j_th": efficiency,
        "uptime_s": elapsed,
        "accepted": accepted,
        "rejected": rejected,
        "hardware_errors": hw_errors,
        "pool_url": pool_url,
        "pool_user": pool_user,
        "pools": pools,
        "latency_ms": latency_ms if (api_verified or web_available) else None,
        "api_error": api_error,
        "web_scheme": identity.get("scheme", ""),
        "web_server": identity.get("server", ""),
        "web_realm": identity.get("realm", ""),
    }


def is_confirmed_asic(device):
    """Return True only when ASIC-specific evidence was positively verified."""
    device = dict(device or {})
    return bool(
        device.get("api_verified")
        or device.get("recognized_web_asic")
    )


def classify_probe(probe):
    """
    Convert a discovery port probe into a conservative candidate record.
    Opening port 4028 alone is not enough to label a device as an ASIC.
    """
    ip = ensure_private_host(probe["ip"])
    http_available = bool(probe.get("http"))
    https_available = bool(probe.get("https"))
    cgminer_port_open = bool(probe.get("cgminer"))

    if http_available or https_available:
        verification = "CANDIDATE"
        model = "Network management interface"
        status = "Candidate"
    elif cgminer_port_open:
        verification = "CANDIDATE"
        model = "TCP 4028 candidate"
        status = "Candidate"
    else:
        verification = "UNVERIFIED"
        model = "Unknown network device"
        status = "Unknown"

    return {
        "ip": ip,
        "model": model,
        "vendor": "",
        "firmware": "",
        "verification": verification,
        "status": status,
        "api_verified": False,
        "recognized_web_asic": False,
        "web_available": http_available or https_available,
        "http_available": http_available,
        "https_available": https_available,
        "can_open_web": False,
        "can_switch_pool": False,
        "can_restart": False,
        "hashrate_hs": 0.0,
        "temperature_c": None,
        "fan_rpm": None,
        "power_w": None,
        "efficiency_j_th": None,
        "uptime_s": 0,
        "accepted": 0,
        "rejected": 0,
        "hardware_errors": 0,
        "pool_url": "",
        "pool_user": "",
        "pools": [],
        "latency_ms": None,
        "api_error": "",
        "web_scheme": "https" if https_available else ("http" if http_available else ""),
        "web_server": "",
        "web_realm": "",
        "cgminer_port_open": cgminer_port_open,
    }


def restart_miner(ip, timeout=3.0):
    return cgminer_command(ip, "restart", timeout=timeout)


def switch_pool(ip, pool_index, timeout=3.0):
    pool_index = int(pool_index)
    if pool_index < 0:
        raise ValueError("Pool index must be zero or greater.")
    return cgminer_command(ip, "switchpool", parameter=pool_index, timeout=timeout)


def _normalized_pool_url(value):
    return str(value or "").strip().rstrip("/").lower()


def pool_index_for_url(pools, target_url):
    target = _normalized_pool_url(target_url)
    if not target:
        return None
    for fallback_index, pool in enumerate(list(pools or [])):
        if not isinstance(pool, dict):
            continue
        value = pool.get("URL", pool.get("Stratum URL", ""))
        if _normalized_pool_url(value) != target:
            continue
        for key in ("POOL", "Pool", "pool"):
            try:
                if key in pool:
                    return int(pool[key])
            except (TypeError, ValueError):
                pass
        return fallback_index
    return None


def add_pool(ip, pool_url, worker, password="x", timeout=4.0):
    ip = ensure_private_host(ip)
    pool_url = str(pool_url or "").strip()
    worker = str(worker or "").strip()
    password = str(password or "x")
    if not pool_url:
        raise ValueError("Pool URL is required.")
    if "," in pool_url or "," in worker or "," in password:
        raise ValueError("Pool URL/worker/password cannot contain commas for cgminer addpool.")
    return cgminer_command(
        ip,
        "addpool",
        parameter=f"{pool_url},{worker},{password}",
        timeout=timeout,
    )


def assign_pool(ip, pool_url, worker, password="x", timeout=4.0):
    ip = ensure_private_host(ip)
    try:
        pools_response = cgminer_command(ip, "pools", timeout=timeout)
    except Exception as exc:
        raise RuntimeError(f"Could not read ASIC pool configuration: {exc}") from exc

    _, _, pools = _extract_pool(pools_response)
    index = pool_index_for_url(pools, pool_url)
    added = False

    if index is None:
        try:
            add_pool(ip, pool_url, worker, password=password, timeout=timeout)
            added = True
        except Exception as exc:
            raise RuntimeError(
                "ASIC firmware rejected automatic addpool. Open the miner Web UI "
                "and enter the Miner Studio Solo Bridge endpoint manually. "
                f"Device response: {exc}"
            ) from exc

        time.sleep(0.15)
        pools_response = cgminer_command(ip, "pools", timeout=timeout)
        _, _, pools = _extract_pool(pools_response)
        index = pool_index_for_url(pools, pool_url)

    if index is None:
        raise RuntimeError(
            "The local solo pool was added but its index could not be resolved. "
            "Verify the pool list in the ASIC Web UI."
        )

    switch_pool(ip, index, timeout=timeout)
    return {
        "ok": True,
        "pool_index": int(index),
        "added": bool(added),
        "pool_url": str(pool_url),
        "worker": str(worker),
    }
