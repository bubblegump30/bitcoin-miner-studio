import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path


NETWORKS = {
    "main": {"rpc_port": 8332, "subdir": "", "section": "main"},
    "testnet": {"rpc_port": 18332, "subdir": "testnet3", "section": "test"},
    "testnet4": {"rpc_port": 48332, "subdir": "testnet4", "section": "testnet4"},
    "signet": {"rpc_port": 38332, "subdir": "signet", "section": "signet"},
    "regtest": {"rpc_port": 18443, "subdir": "regtest", "section": "regtest"},
}
PORT_TO_NETWORK = {v["rpc_port"]: k for k, v in NETWORKS.items()}


class CoreSetupError(RuntimeError):
    def __init__(self, message, kind="configuration"):
        super().__init__(message)
        self.kind = kind


def _truthy(value):
    if value is None:
        return None
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def default_data_dirs(env=None, platform_name=None, home=None):
    env = dict(os.environ if env is None else env)
    platform_name = platform_name or sys.platform
    home = Path(home or Path.home())
    values = []
    if platform_name.startswith("win"):
        localapp = env.get("LOCALAPPDATA")
        appdata = env.get("APPDATA")
        # Current Bitcoin Core uses %LOCALAPPDATA%\Bitcoin by default on Windows.
        # Keep %APPDATA%\Bitcoin as a legacy fallback for older installations.
        if localapp:
            values.append(Path(localapp) / "Bitcoin")
        if appdata:
            values.append(Path(appdata) / "Bitcoin")
    elif platform_name == "darwin":
        values.append(home / "Library" / "Application Support" / "Bitcoin")
    else:
        values.append(home / ".bitcoin")
    # Stable de-duplication.
    out = []
    seen = set()
    for p in values:
        key = str(p)
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out


def parse_bitcoin_conf(path):
    """Parse the subset of bitcoin.conf needed by the setup assistant."""
    path = Path(path)
    parsed = {"global": {}, "sections": {}}
    if not path.exists():
        return parsed
    section = "global"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return parsed
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip().lower() or "global"
            parsed["sections"].setdefault(section, {})
            continue
        # Bitcoin config values do not require inline-comment parsing for the
        # keys used here; preserve # inside passwords/paths rather than corrupting them.
        if "=" in line:
            key, value = line.split("=", 1)
        else:
            key, value = line, "1"
        key = key.strip().lower()
        value = value.strip().strip('"')
        if section == "global":
            parsed["global"][key] = value
        else:
            parsed["sections"].setdefault(section, {})[key] = value
    return parsed


def detect_network(parsed):
    g = parsed.get("global", {})
    # Most-specific local/development chains first.
    if _truthy(g.get("regtest")):
        return "regtest"
    if _truthy(g.get("signet")):
        return "signet"
    if _truthy(g.get("testnet4")):
        return "testnet4"
    if _truthy(g.get("testnet")) or _truthy(g.get("test")):
        return "testnet"
    chain = str(g.get("chain", "")).strip().lower()
    aliases = {"mainnet": "main", "test": "testnet", "testnet3": "testnet"}
    if chain in NETWORKS:
        return chain
    if chain in aliases:
        return aliases[chain]
    return "main"


def effective_config(parsed, network):
    result = dict(parsed.get("global", {}))
    section = NETWORKS.get(network, NETWORKS["main"])["section"]
    result.update(parsed.get("sections", {}).get(section, {}))
    # Accept network-prefixed settings as well.
    prefix_names = {"main": "main", "testnet": "test", "testnet4": "testnet4", "signet": "signet", "regtest": "regtest"}
    prefix = prefix_names.get(network, network) + "."
    for key, value in parsed.get("global", {}).items():
        if key.startswith(prefix):
            result[key[len(prefix):]] = value
    return result


def network_data_dir(data_dir, network):
    info = NETWORKS.get(network, NETWORKS["main"])
    return Path(data_dir) / info["subdir"] if info["subdir"] else Path(data_dir)


def resolve_cookie_path(data_dir, network, effective=None):
    effective = effective or {}
    net_dir = network_data_dir(data_dir, network)
    custom = str(effective.get("rpccookiefile", "") or "").strip()
    if custom:
        p = Path(os.path.expandvars(os.path.expanduser(custom)))
        if not p.is_absolute():
            p = net_dir / p
        return p
    return net_dir / ".cookie"


def read_rpc_cookie(path):
    path = Path(path)
    if not path.exists():
        raise CoreSetupError(f"Bitcoin Core cookie file was not found: {path}", kind="authentication")
    try:
        raw = path.read_text(encoding="utf-8", errors="strict").strip()
    except OSError as exc:
        raise CoreSetupError(f"Could not read Bitcoin Core cookie file: {exc}", kind="authentication") from exc
    if ":" not in raw:
        raise CoreSetupError("Bitcoin Core cookie file is malformed.", kind="authentication")
    username, password = raw.split(":", 1)
    if not username or not password:
        raise CoreSetupError("Bitcoin Core cookie file is incomplete.", kind="authentication")
    return username, password


def _socket_listening(host, port, timeout=0.12):
    try:
        with socket.create_connection((host, int(port)), timeout=float(timeout)):
            return True
    except OSError:
        return False


def _known_executables(env=None, platform_name=None, configured=None, home=None):
    env = dict(os.environ if env is None else env)
    platform_name = platform_name or sys.platform
    found = []

    configured = str(configured or "").strip()
    if configured:
        try:
            p = Path(os.path.expandvars(os.path.expanduser(configured)))
            if p.exists() and p.is_file():
                found.append(p)
        except OSError:
            pass

    for name in ("bitcoin-qt", "bitcoind", "bitcoin-cli"):
        path = shutil.which(name)
        if path:
            found.append(Path(path))
    if platform_name.startswith("win"):
        roots = [env.get("ProgramFiles"), env.get("ProgramFiles(x86)"), env.get("LOCALAPPDATA")]
        candidates = []
        for root in roots:
            if not root:
                continue
            r = Path(root)
            candidates += [
                r / "Bitcoin" / "bitcoin-qt.exe",
                r / "Bitcoin" / "daemon" / "bitcoind.exe",
                r / "Bitcoin" / "daemon" / "bitcoin-cli.exe",
                r / "Programs" / "Bitcoin" / "bitcoin-qt.exe",
                r / "Programs" / "Bitcoin" / "daemon" / "bitcoind.exe",
            ]
        found.extend(p for p in candidates if p.exists())
    if platform_name.startswith("win"):
        found.extend(_registry_executables(platform_name=platform_name))
        system_drive = env.get("SystemDrive") or "C:"
        user_home = Path(home or Path.home())
        portable = [
            Path(system_drive) / "Bitcoin" / "bitcoin-qt.exe",
            Path(system_drive) / "Bitcoin" / "daemon" / "bitcoind.exe",
            user_home / "Bitcoin" / "bitcoin-qt.exe",
            user_home / "Bitcoin" / "daemon" / "bitcoind.exe",
        ]

        # Common extracted/portable locations without performing a slow full-drive scan.
        for base in (user_home / "Desktop", user_home / "Downloads"):
            if base.exists():
                try:
                    for child in base.glob("bitcoin*"):
                        portable.extend([
                            child / "bitcoin-qt.exe",
                            child / "bin" / "bitcoin-qt.exe",
                            child / "daemon" / "bitcoind.exe",
                            child / "bin" / "bitcoind.exe",
                        ])
                except OSError:
                    pass

        found.extend(p for p in portable if p.exists())

    out = []
    seen = set()
    for p in found:
        key = str(p).lower()
        if key not in seen:
            seen.add(key)
            out.append(p)
    return out



def _registry_executables(platform_name=None):
    """Best-effort Windows App Paths lookup without requiring pywin32."""
    platform_name = platform_name or sys.platform
    if not platform_name.startswith("win"):
        return []
    try:
        import winreg
    except Exception:
        return []

    names = ("bitcoin-qt.exe", "bitcoind.exe", "bitcoin-cli.exe")
    hives = (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE)
    found = []
    for hive in hives:
        for name in names:
            key_path = rf"Software\Microsoft\Windows\CurrentVersion\App Paths\{name}"
            try:
                with winreg.OpenKey(hive, key_path) as key:
                    value, _ = winreg.QueryValueEx(key, None)
                    path = Path(str(value).strip().strip('"'))
                    if path.exists():
                        found.append(path)
            except OSError:
                pass
    return found



def _registry_data_dirs(platform_name=None):
    """Read Bitcoin-Qt's saved Windows data-directory selection."""
    platform_name = platform_name or sys.platform
    if not platform_name.startswith("win"):
        return []
    try:
        import winreg
    except Exception:
        return []

    keys = (
        r"SOFTWARE\Bitcoin\Bitcoin-Qt",
        r"SOFTWARE\Bitcoin\Bitcoin-Qt-testnet",
        r"SOFTWARE\Bitcoin\Bitcoin-Qt-testnet4",
        r"SOFTWARE\Bitcoin\Bitcoin-Qt-signet",
        r"SOFTWARE\Bitcoin\Bitcoin-Qt-regtest",
    )
    found = []
    for key_path in keys:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                value, _ = winreg.QueryValueEx(key, "strDataDir")
                path = Path(os.path.expandvars(os.path.expanduser(str(value).strip().strip('"'))))
                if path.exists() and path.is_dir():
                    found.append(path)
        except OSError:
            pass

    out, seen = [], set()
    for path in found:
        key = str(path).lower()
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out



def _path_key(value):
    """Normalize a path for data-directory identity comparisons.

    Windows drive-letter paths are normalized without requiring the current
    host to be Windows, which keeps the release self-tests deterministic.
    """
    text = str(value or "").strip().strip('"')
    if not text:
        return ""
    text = os.path.expandvars(os.path.expanduser(text))
    if re.match(r"^[A-Za-z]:[\\/]", text):
        return text.replace("/", "\\").rstrip("\\").casefold()
    try:
        return os.path.normcase(os.path.normpath(str(Path(text).resolve(strict=False))))
    except Exception:
        return os.path.normcase(os.path.normpath(text))


def same_data_dir(left, right):
    a, b = _path_key(left), _path_key(right)
    return bool(a and b and a == b)


def core_data_dir_guard(configured_data_dir, running_processes=None, registry_dirs=None, *, process_running=False):
    """Evaluate whether a running Core process is tied to the intended data dir.

    The guard never guesses that an arbitrary running Bitcoin Core process is
    safe. An explicit -datadir match is strongest. Bitcoin-Qt's saved registry
    directory is accepted as a likely match only when the process command line
    does not expose -datadir.
    """
    configured = str(configured_data_dir or "").strip()
    running_processes = [dict(x or {}) for x in (running_processes or [])]
    registry_dirs = [str(x or "").strip() for x in (registry_dirs or []) if str(x or "").strip()]
    process_running = bool(process_running or running_processes)

    if not configured:
        return {
            "status": "UNCONFIGURED",
            "safe": False,
            "configured_data_dir": "",
            "message": (
                "No Bitcoin data directory is pinned. Choose the intended data folder "
                "before Miner Studio launches Bitcoin Core."
            ),
        }

    explicit_dirs = [
        str(item.get("data_dir") or "").strip()
        for item in running_processes
        if str(item.get("data_dir") or "").strip()
    ]
    implicit_count = sum(1 for item in running_processes if not str(item.get("data_dir") or "").strip())

    if not process_running:
        return {
            "status": "READY",
            "safe": True,
            "configured_data_dir": configured,
            "message": f"Launch is pinned to: {configured}",
        }

    mismatched_explicit = [value for value in explicit_dirs if not same_data_dir(value, configured)]
    matching_explicit = [value for value in explicit_dirs if same_data_dir(value, configured)]

    if mismatched_explicit:
        return {
            "status": "MISMATCH",
            "safe": False,
            "configured_data_dir": configured,
            "running_data_dirs": explicit_dirs,
            "message": (
                "Bitcoin Core is already running with a different explicit data directory. "
                "Close that Core instance before launching the configured node."
            ),
        }

    if matching_explicit:
        return {
            "status": "MATCH",
            "safe": True,
            "configured_data_dir": configured,
            "running_data_dirs": explicit_dirs,
            "message": f"Running Bitcoin Core explicitly matches: {configured}",
        }

    registry_match = any(same_data_dir(value, configured) for value in registry_dirs)
    if implicit_count and registry_match:
        return {
            "status": "LIKELY_MATCH",
            "safe": True,
            "configured_data_dir": configured,
            "message": (
                "Running Bitcoin-Qt has no explicit -datadir argument, but its saved "
                "Windows data directory matches the configured Miner Studio folder."
            ),
        }

    if implicit_count and registry_dirs and not registry_match:
        return {
            "status": "MISMATCH",
            "safe": False,
            "configured_data_dir": configured,
            "registry_data_dirs": registry_dirs,
            "message": (
                "Running Bitcoin-Qt has no explicit -datadir argument and its saved "
                "Windows data directory does not match Miner Studio's configured folder."
            ),
        }

    return {
        "status": "UNVERIFIED_RUNNING",
        "safe": False,
        "configured_data_dir": configured,
        "message": (
            "Bitcoin Core is already running, but Miner Studio cannot prove which data "
            "directory it is using. Close it and relaunch it from Miner Studio so "
            "-datadir is explicit."
        ),
    }


def build_bitcoin_core_launch_args(executable, data_dir):
    """Return a deterministic Bitcoin Core launch command with mandatory -datadir."""
    exe = validate_core_executable(executable)
    data_dir = str(data_dir or "").strip()
    if not data_dir:
        raise CoreSetupError(
            "No Bitcoin data directory is pinned. Choose Data Folder before starting Bitcoin Core.",
            kind="configuration",
        )
    d = Path(os.path.expandvars(os.path.expanduser(data_dir)))
    if not d.exists() or not d.is_dir():
        raise CoreSetupError(
            f"Configured Bitcoin data directory does not exist: {d}. "
            "Miner Studio will not fall back to Bitcoin Core's default profile directory.",
            kind="configuration",
        )
    return [str(exe), f"-datadir={d}"]



def _extract_datadir_from_command_line(command_line):
    text = str(command_line or "")
    for pattern in (
        r'(?:^|\s)-datadir=(?:"([^"]+)"|([^\s]+))',
        r'(?:^|\s)-datadir\s+(?:"([^"]+)"|([^\s]+))',
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = next((g for g in match.groups() if g), "")
            if value:
                return Path(os.path.expandvars(os.path.expanduser(value)))
    return None


def _windows_running_core_processes():
    """Return running bitcoin-qt/bitcoind path and command line via CIM."""
    if not sys.platform.startswith("win"):
        return []

    ps_script = r"""
$items = Get-CimInstance Win32_Process |
  Where-Object { $_.Name -eq 'bitcoin-qt.exe' -or $_.Name -eq 'bitcoind.exe' } |
  Select-Object Name, ExecutablePath, CommandLine, ProcessId
if ($items) { $items | ConvertTo-Json -Compress }
"""
    try:
        proc = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = (proc.stdout or "").strip()
        if not raw:
            return []
        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload = [payload]
        out = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            exe = str(item.get("ExecutablePath") or "").strip()
            cmd = str(item.get("CommandLine") or "").strip()
            datadir = _extract_datadir_from_command_line(cmd)
            out.append({
                "name": str(item.get("Name") or "").strip(),
                "executable": exe,
                "command_line": cmd,
                "pid": item.get("ProcessId"),
                "data_dir": str(datadir) if datadir else "",
            })
        return out
    except Exception:
        return []


def _existing_core_markers(candidate):
    candidate = Path(candidate)
    if not candidate.exists() or not candidate.is_dir():
        return False
    if (candidate / "bitcoin.conf").exists():
        return True
    for info in NETWORKS.values():
        net = candidate / info["subdir"] if info["subdir"] else candidate
        if (net / ".cookie").exists() or (net / "blocks").exists() or (net / "chainstate").exists():
            return True
    return False


def _first_existing_dir(candidates):
    for candidate in candidates:
        try:
            if Path(candidate).exists() and Path(candidate).is_dir():
                return Path(candidate)
        except OSError:
            pass
    return None

def _process_running(platform_name=None):
    platform_name = platform_name or sys.platform
    try:
        if platform_name.startswith("win"):
            proc = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                timeout=2,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            text = (proc.stdout or "").lower()
            return "bitcoin-qt.exe" in text or "bitcoind.exe" in text
        proc = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=2)
        text = (proc.stdout or "").lower()
        return "bitcoin-qt" in text or "bitcoind" in text
    except Exception:
        return False


def recommended_config_snippet(network="main"):
    lines = [
        "server=1",
        "rpcbind=127.0.0.1",
        "rpcallowip=127.0.0.1",
    ]
    if network == "testnet":
        lines.insert(0, "testnet=1")
    elif network == "testnet4":
        lines.insert(0, "testnet4=1")
    elif network == "signet":
        lines.insert(0, "signet=1")
    elif network == "regtest":
        lines.insert(0, "regtest=1")
    lines += ["", "# Bitcoin Miner Studio can use Bitcoin Core's .cookie authentication."]
    return "\n".join(lines)



def validate_core_executable(path):
    """Validate a manually selected Bitcoin Core executable."""
    if not path:
        raise CoreSetupError("No Bitcoin Core executable was selected.", kind="configuration")
    p = Path(os.path.expandvars(os.path.expanduser(str(path)))).resolve()
    if not p.exists() or not p.is_file():
        raise CoreSetupError(f"Bitcoin Core executable was not found: {p}", kind="configuration")
    name = p.name.lower()
    if name not in {"bitcoin-qt.exe", "bitcoind.exe", "bitcoin-qt", "bitcoind"}:
        raise CoreSetupError(
            "Select bitcoin-qt.exe or bitcoind.exe. bitcoin-cli is not the node executable.",
            kind="configuration",
        )
    return p


def launch_bitcoin_core(executable, data_dir=""):
    """Launch Bitcoin Core with an explicit, validated -datadir every time."""
    args = build_bitcoin_core_launch_args(executable, data_dir)
    exe = Path(args[0])

    kwargs = {}
    if sys.platform.startswith("win"):
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        subprocess.Popen(args, cwd=str(exe.parent), **kwargs)
    except OSError as exc:
        raise CoreSetupError(f"Could not start Bitcoin Core: {exc}", kind="launch") from exc
    return str(exe)


def detect_bitcoin_core(cfg=None, *, env=None, platform_name=None, home=None, socket_checker=None):
    cfg = dict(cfg or {})
    env = dict(os.environ if env is None else env)
    platform_name = platform_name or sys.platform
    socket_checker = socket_checker or _socket_listening

    configured_dir = str(cfg.get("core_data_dir", "") or "").strip()
    defaults = default_data_dirs(env=env, platform_name=platform_name, home=home)
    expected_default = defaults[0] if defaults else Path(home or Path.home()) / ".bitcoin"

    running_processes = _windows_running_core_processes() if platform_name.startswith("win") else []
    registry_dirs = _registry_data_dirs(platform_name=platform_name) if platform_name.startswith("win") else []

    candidates = []
    if configured_dir:
        candidates.append(Path(configured_dir))
    for item in running_processes:
        if item.get("data_dir"):
            candidates.append(Path(item["data_dir"]))
    candidates += registry_dirs
    candidates += defaults

    # A path is "detected" only when it exists and contains Core state/config.
    data_dir = None
    for candidate in candidates:
        if _existing_core_markers(candidate):
            data_dir = Path(candidate)
            break

    # If Core has been run but has no config/cookie yet, an existing default folder
    # is still meaningful. Do not create or claim a missing directory.
    if data_dir is None:
        existing_default = _first_existing_dir(candidates)
        if existing_default is not None:
            data_dir = existing_default

    data_dir_exists = bool(data_dir and data_dir.exists())
    conf_path = (data_dir / "bitcoin.conf") if data_dir else None
    parsed = parse_bitcoin_conf(conf_path) if conf_path else {"global": {}, "sections": {}}
    global_cfg = parsed.get("global", {})

    override = str(global_cfg.get("datadir", "") or "").strip()
    if override and data_dir:
        override_path = Path(os.path.expandvars(os.path.expanduser(override)))
        if not override_path.is_absolute():
            override_path = data_dir / override_path
        if override_path.exists() and override_path.is_dir() and override_path != data_dir:
            data_dir = override_path
            data_dir_exists = True
            conf_path = data_dir / "bitcoin.conf" if (data_dir / "bitcoin.conf").exists() else conf_path
            parsed = parse_bitcoin_conf(conf_path) if conf_path else {"global": {}, "sections": {}}

    network = str(cfg.get("core_network", "") or "").strip().lower()
    if network not in NETWORKS:
        network = detect_network(parsed)
    effective = effective_config(parsed, network)

    try:
        rpc_port = int(effective.get("rpcport", NETWORKS[network]["rpc_port"]))
    except (TypeError, ValueError):
        rpc_port = NETWORKS[network]["rpc_port"]

    listening = {}
    for name, info in NETWORKS.items():
        port = info["rpc_port"]
        try:
            listening[name] = bool(socket_checker("127.0.0.1", port))
        except Exception:
            listening[name] = False
    active_networks = [name for name, value in listening.items() if value]
    configured_listening = bool(socket_checker("127.0.0.1", rpc_port)) if rpc_port not in PORT_TO_NETWORK else listening.get(network, False)
    if not configured_listening and len(active_networks) == 1:
        network = active_networks[0]
        effective = effective_config(parsed, network)
        try:
            rpc_port = int(effective.get("rpcport", NETWORKS[network]["rpc_port"]))
        except (TypeError, ValueError):
            rpc_port = NETWORKS[network]["rpc_port"]
        configured_listening = True

    cookie_path = resolve_cookie_path(data_dir, network, effective) if data_dir else None
    expected_cookie_path = resolve_cookie_path(expected_default, network, effective)
    cookie_exists = bool(cookie_path and cookie_path.exists())
    cookie_user = ""
    if cookie_exists:
        try:
            cookie_user, _ = read_rpc_cookie(cookie_path)
        except Exception:
            pass

    executables = _known_executables(
        env=env,
        platform_name=platform_name,
        configured=cfg.get("core_executable", ""),
        home=home,
    )
    for item in running_processes:
        exe = str(item.get("executable") or "").strip()
        if exe:
            try:
                exe_path = Path(exe)
                if exe_path.exists() and exe_path.is_file():
                    executables.insert(0, exe_path)
            except OSError:
                pass

    exe_out, exe_seen = [], set()
    for exe in executables:
        key = str(exe).lower()
        if key not in exe_seen:
            exe_seen.add(key)
            exe_out.append(exe)
    executables = exe_out
    server_value = _truthy(effective.get("server"))
    process_running = bool(running_processes) or _process_running(platform_name=platform_name)

    # Pin launch identity to an explicitly configured directory when present.
    # Otherwise use the verified detected directory. Never silently replace an
    # explicit user selection merely because another Core profile is running.
    launch_data_dir = configured_dir or (str(data_dir) if data_dir_exists else "")
    guard = core_data_dir_guard(
        launch_data_dir,
        running_processes,
        registry_dirs,
        process_running=process_running,
    )

    config_exists = bool(conf_path and conf_path.exists())
    installation_found = bool(executables or process_running)
    detected = bool(data_dir_exists or config_exists or cookie_exists or installation_found or configured_listening)

    remediation = []
    if not installation_found and not data_dir_exists and not configured_listening:
        remediation.append(
            "Bitcoin Core was not found. Use Locate Core EXE if it is installed somewhere custom, "
            "or use Download Bitcoin Core if it is not installed."
        )
    elif not process_running and not configured_listening:
        remediation.append("Start Bitcoin Core or bitcoind.")
    if server_value is False:
        remediation.append("Enable server=1 in bitcoin.conf and restart Bitcoin Core.")
    elif server_value is None and data_dir_exists and not configured_listening:
        remediation.append("If using Bitcoin Core GUI, add server=1 to bitcoin.conf and restart it.")
    if data_dir_exists and not cookie_exists:
        remediation.append("Cookie authentication becomes available after Bitcoin Core starts; manual rpcuser/rpcpassword remains supported.")
    if not configured_listening:
        remediation.append(f"Expected local RPC endpoint for {network}: http://127.0.0.1:{rpc_port}")
    if guard.get("status") == "MISMATCH":
        remediation.insert(
            0,
            "Bitcoin Core data-directory mismatch detected. Close the currently running Core "
            "instance and use Start Bitcoin Core in Miner Studio to relaunch the pinned data folder.",
        )
    elif guard.get("status") == "UNVERIFIED_RUNNING":
        remediation.insert(
            0,
            "Bitcoin Core is running but its data directory cannot be verified. Close it and "
            "relaunch it from Miner Studio so -datadir is explicit.",
        )
    elif guard.get("status") == "UNCONFIGURED":
        remediation.insert(
            0,
            "Choose the intended Bitcoin data directory before launching Core.",
        )

    return {
        "detected": detected,
        "installation_found": installation_found,
        "data_dir": str(data_dir) if data_dir else "",
        "data_dir_exists": data_dir_exists,
        "expected_data_dir": str(expected_default),
        "config_file": str(conf_path) if conf_path else "",
        "config_exists": config_exists,
        "network": network,
        "rpc_port": rpc_port,
        "rpc_url": f"http://127.0.0.1:{rpc_port}",
        "rpc_listening": bool(configured_listening),
        "listening_networks": active_networks,
        "cookie_path": str(cookie_path) if cookie_path else "",
        "expected_cookie_path": str(expected_cookie_path),
        "cookie_exists": cookie_exists,
        "cookie_user": cookie_user,
        "auth_mode_recommended": "cookie" if cookie_exists else "password",
        "server_enabled": server_value,
        "process_running": process_running,
        "executable": str(executables[0]) if executables else "",
        "executables": [str(p) for p in executables],
        "running_processes": running_processes,
        "registry_data_dirs": [str(p) for p in registry_dirs],
        "configured_data_dir": configured_dir,
        "launch_data_dir": launch_data_dir,
        "data_dir_guard_status": guard.get("status"),
        "data_dir_guard_safe": bool(guard.get("safe")),
        "data_dir_guard_message": guard.get("message", ""),
        "remediation": remediation,
        "config_snippet": recommended_config_snippet(network),
    }


def auto_config_values(detection, current=None):
    detection = dict(detection or {})
    current = dict(current or {})
    current_data_dir = str(current.get("core_data_dir", "") or "").strip()
    detected_data_dir = (
        str(detection.get("data_dir") or "").strip()
        if detection.get("data_dir_exists")
        else ""
    )
    selected_data_dir = current_data_dir or detected_data_dir

    current_executable = str(current.get("core_executable", "") or "").strip()
    detected_executable = (
        str(detection.get("executable") or "").strip()
        if detection.get("installation_found")
        else ""
    )

    # Only adopt a detected cookie when it belongs to the selected data dir.
    same_detected_dir = (
        bool(selected_data_dir and detected_data_dir)
        and same_data_dir(selected_data_dir, detected_data_dir)
    )
    detected_cookie = (
        str(detection.get("cookie_path") or "").strip()
        if detection.get("cookie_exists") and (not current_data_dir or same_detected_dir)
        else ""
    )

    result = {
        "rpc_url": detection.get("rpc_url") or current.get("rpc_url") or "http://127.0.0.1:8332",
        "core_network": detection.get("network") or current.get("core_network") or "main",
        # Preserve an explicitly pinned directory instead of silently switching
        # to another/default profile discovered while Core is running.
        "core_data_dir": selected_data_dir,
        "core_executable": current_executable or detected_executable,
        "core_cookie_path": detected_cookie or current.get("core_cookie_path", ""),
        "core_auth_mode": detection.get("auth_mode_recommended") or current.get("core_auth_mode") or "password",
    }
    if detection.get("cookie_user"):
        result["rpc_user"] = detection["cookie_user"]
    elif current.get("rpc_user"):
        result["rpc_user"] = current["rpc_user"]
    return result


def resolve_rpc_credentials(cfg, stored_password=""):
    mode = str((cfg or {}).get("core_auth_mode", "password") or "password").strip().lower()
    if mode == "cookie":
        cookie_path = str((cfg or {}).get("core_cookie_path", "") or "").strip()
        if not cookie_path:
            raise CoreSetupError("Cookie authentication is selected but no cookie file is configured.", kind="authentication")
        return read_rpc_cookie(cookie_path)
    return str((cfg or {}).get("rpc_user", "") or ""), str(stored_password or "")


def detection_report(d):
    d = dict(d or {})
    yesno = lambda x: "Yes" if x else "No"
    server = "Yes" if d.get("server_enabled") is True else ("No" if d.get("server_enabled") is False else "Not set")
    data_display = d.get("data_dir") if d.get("data_dir_exists") else "Not found"
    conf_display = d.get("config_file") if d.get("config_exists") else "Not found"
    cookie_display = d.get("cookie_path") if d.get("cookie_exists") else "Not found"
    lines = [
        "BITCOIN CORE SETUP DETECTION",
        "",
        f"Detected: {yesno(d.get('detected'))}",
        f"Installation found: {yesno(d.get('installation_found'))}",
        f"Process running: {yesno(d.get('process_running'))}",
        f"RPC listening: {yesno(d.get('rpc_listening'))}",
        f"Network: {d.get('network', 'main')}",
        f"RPC URL: {d.get('rpc_url', '—')}",
        f"Data directory: {data_display}",
        f"Pinned launch directory: {d.get('launch_data_dir') or 'Not configured'}",
        f"Data-dir guard: {d.get('data_dir_guard_status') or 'UNKNOWN'}",
        f"Data-dir guard detail: {d.get('data_dir_guard_message') or '—'}",
        f"Expected default directory: {d.get('expected_data_dir', '—')}",
        f"bitcoin.conf: {conf_display}",
        f"server=1: {server}",
        f"Cookie file: {cookie_display}",
        f"Cookie available: {yesno(d.get('cookie_exists'))}",
        f"Executable: {d.get('executable') or 'Not found'}",
    ]
    remediation = d.get("remediation") or []
    if remediation:
        lines += ["", "RECOMMENDED NEXT STEPS"] + [f"- {x}" for x in remediation]
    return "\n".join(lines)

