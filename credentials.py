import os

APP_PREFIX = "BitcoinMinerStudio"
POOL_TARGET = f"{APP_PREFIX}/Pool"
RPC_TARGET = f"{APP_PREFIX}/BitcoinCore"
POOL_PROFILE_PREFIX = f"{APP_PREFIX}/PoolProfile"


def pool_profile_target(profile_id: str):
    safe = "".join(ch for ch in str(profile_id or "").strip().lower() if ch.isalnum() or ch in "-_" )[:64]
    if not safe:
        raise ValueError("Pool profile ID is required.")
    return f"{POOL_PROFILE_PREFIX}/{safe}"


def backend_name():
    return "Windows Credential Manager" if os.name == "nt" else "session-only credentials"


if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    CRED_TYPE_GENERIC = 1
    CRED_PERSIST_LOCAL_MACHINE = 2
    ERROR_NOT_FOUND = 1168

    class FILETIME(ctypes.Structure):
        _fields_ = [
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        ]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    advapi32.CredWriteW.restype = wintypes.BOOL
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CREDENTIALW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi32.CredDeleteW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None


def write_secret(target: str, username: str, secret: str):
    if os.name != "nt":
        return False
    if not secret:
        delete_secret(target)
        return True

    blob = secret.encode("utf-8")
    if len(blob) > 5120:
        raise ValueError("Credential is too large.")

    buf = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob)
    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = "Stored by Bitcoin Miner Studio"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte))
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = username or ""

    if not advapi32.CredWriteW(ctypes.byref(cred), 0):
        raise ctypes.WinError(ctypes.get_last_error())
    return True


def read_secret(target: str):
    if os.name != "nt":
        return None
    pcred = ctypes.POINTER(CREDENTIALW)()
    ok = advapi32.CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(pcred))
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return None
        raise ctypes.WinError(err)
    try:
        cred = pcred.contents
        if not cred.CredentialBlob or not cred.CredentialBlobSize:
            return ""
        raw = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize)
        return raw.decode("utf-8")
    finally:
        advapi32.CredFree(pcred)


def delete_secret(target: str):
    if os.name != "nt":
        return False
    ok = advapi32.CredDeleteW(target, CRED_TYPE_GENERIC, 0)
    if not ok:
        err = ctypes.get_last_error()
        if err == ERROR_NOT_FOUND:
            return True
        raise ctypes.WinError(err)
    return True
