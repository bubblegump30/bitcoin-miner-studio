"""Bitcoin Miner Studio v2 runtime context and canonical local paths.

This module deliberately contains no mining controls. It centralizes application
identity and filesystem locations so backend services do not each invent their
own paths or version metadata.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    app_data: Path
    exports: Path
    candidates: Path
    staging: Path
    support: Path

    def ensure(self) -> "RuntimePaths":
        # Only user-data directories are created. The application source folder
        # is never rewritten by runtime initialization.
        for path in (self.app_data, self.exports, self.candidates, self.staging, self.support):
            path.mkdir(parents=True, exist_ok=True)
        return self


@dataclass(frozen=True)
class RuntimeContext:
    product: str
    version: str
    publisher: str
    channel: str
    architecture: str
    paths: RuntimePaths

    @classmethod
    def create(
        cls,
        *,
        root: Path,
        version: str,
        product: str = "Bitcoin Miner Studio",
        publisher: str = "Purple Dragon Foundation ltd",
        channel: str = "Stable",
        app_data: Path | None = None,
    ) -> "RuntimeContext":
        root = Path(root).resolve()
        data = Path(app_data or (Path.home() / ".bitcoin-miner-studio")).expanduser().resolve()
        paths = RuntimePaths(
            root=root,
            app_data=data,
            exports=data / "exports",
            candidates=data / "candidates",
            staging=data / "update-center" / "staging",
            support=data / "support",
        ).ensure()
        return cls(
            product=str(product),
            version=str(version),
            publisher=str(publisher),
            channel=str(channel),
            architecture="BMS-ARCH-2",
            paths=paths,
        )

    def public_snapshot(self) -> Dict[str, object]:
        return {
            "product": self.product,
            "version": self.version,
            "publisher": self.publisher,
            "channel": self.channel,
            "architecture": self.architecture,
            "root": str(self.paths.root),
            "app_data": str(self.paths.app_data),
            "exports": str(self.paths.exports),
            "candidate_store": str(self.paths.candidates),
            "support_store": str(self.paths.support),
        }
