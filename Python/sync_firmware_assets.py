#!/usr/bin/env python3
"""Sync WebFlasher sources and Arduino build outputs into docs/firmware.

Usage:
  py sync_firmware_assets.py build   -- Arduino build outputs -> WebFlasher/
  py sync_firmware_assets.py deploy  -- WebFlasher/ -> docs/firmware/
  py sync_firmware_assets.py         -- run build then deploy
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
ARDUINO_BUILD_ROOT = REPO_ROOT / "Arduino" / "Scent" / "build"
WEBFLASHER_ROOT = REPO_ROOT / "WebFlasher"
WEBFLASHER_MANIFEST_PATH = WEBFLASHER_ROOT / "manifest.json"
WEBFLASHER_BIN_DIR = WEBFLASHER_ROOT / "firmware"
WEBFLASHER_FLASH_CONFIG_PATH = WEBFLASHER_ROOT / "flash_config.json"
DOCS_FIRMWARE_ROOT = REPO_ROOT / "docs" / "firmware"
DOCS_BIN_DIR = DOCS_FIRMWARE_ROOT / "firmware"
FLASH_CONFIG_PATH = DOCS_FIRMWARE_ROOT / "flash_config.json"
MANIFEST_PATH = DOCS_FIRMWARE_ROOT / "manifest.json"
STATIC_FILE_NAMES = ("index.html", "style.css", "flasher.js")


@dataclass(slots=True)
class FlashPart:
    address: int
    source_name: str
    target_name: str

    @property
    def relative_path(self) -> str:
        return f"./firmware/{self.target_name}"


def find_build_dir() -> Path:
    candidates = [path for path in ARDUINO_BUILD_ROOT.iterdir() if path.is_dir()]
    for candidate in candidates:
        if (candidate / "flash_args").exists():
            return candidate
    raise FileNotFoundError(f"flash_args was not found under {ARDUINO_BUILD_ROOT}")


def parse_flash_args(build_dir: Path) -> tuple[dict[str, str], list[FlashPart]]:
    flash_args_path = build_dir / "flash_args"
    lines = [line.strip() for line in flash_args_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not lines:
        raise ValueError(f"{flash_args_path} is empty")

    option_tokens = shlex.split(lines[0])
    options: dict[str, str] = {}
    index = 0
    while index < len(option_tokens):
        token = option_tokens[index]
        if token.startswith("--") and index + 1 < len(option_tokens):
            options[token[2:]] = option_tokens[index + 1]
            index += 2
        else:
            index += 1

    parts: list[FlashPart] = []
    for line in lines[1:]:
        address_text, source_name = shlex.split(line)
        parts.append(
            FlashPart(
                address=int(address_text, 16),
                source_name=source_name,
                target_name=rename_output_file(source_name),
            )
        )

    return options, parts


def rename_output_file(source_name: str) -> str:
    lower_name = source_name.lower()
    if lower_name.endswith("boot_app0.bin"):
        return "boot_app0.bin"
    if "bootloader" in lower_name:
        return "bootloader.bin"
    if "partition" in lower_name:
        return "partitions.bin"
    if lower_name.endswith(".bin"):
        return "application.bin"
    raise ValueError(f"Unexpected flash part: {source_name}")


def detect_chip_family(build_dir: Path) -> str:
    build_options_path = build_dir / "build.options.json"
    if not build_options_path.exists():
        return "ESP32"

    build_options = json.loads(build_options_path.read_text(encoding="utf-8"))
    fqbn = build_options.get("fqbn", "")
    if fqbn.startswith("esp32:"):
        return "ESP32"
    return "ESP32"


def deploy_to_docs() -> None:
    """Copy WebFlasher/ contents to docs/firmware/."""
    DOCS_FIRMWARE_ROOT.mkdir(parents=True, exist_ok=True)

    for name in STATIC_FILE_NAMES:
        source_path = WEBFLASHER_ROOT / name
        if not source_path.exists():
            raise FileNotFoundError(f"Missing WebFlasher source file: {source_path}")
        shutil.copy2(source_path, DOCS_FIRMWARE_ROOT / name)

    if not WEBFLASHER_FLASH_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Run 'build' first: {WEBFLASHER_FLASH_CONFIG_PATH}")
    shutil.copy2(WEBFLASHER_FLASH_CONFIG_PATH, FLASH_CONFIG_PATH)

    DOCS_BIN_DIR.mkdir(parents=True, exist_ok=True)
    if WEBFLASHER_BIN_DIR.exists():
        src_bins = list(WEBFLASHER_BIN_DIR.glob("*.bin"))
        expected = {p.name for p in src_bins}
        for existing in DOCS_BIN_DIR.glob("*.bin"):
            if existing.name not in expected:
                existing.unlink()
        for src in src_bins:
            shutil.copy2(src, DOCS_BIN_DIR / src.name)


def load_manifest_metadata() -> dict[str, object]:
    if not WEBFLASHER_MANIFEST_PATH.exists():
        return {
            "name": "匂いセンサファームウェア",
            "version": "generated",
            "new_install_prompt_erase": True,
        }

    manifest = json.loads(WEBFLASHER_MANIFEST_PATH.read_text(encoding="utf-8"))
    return {
        "name": manifest.get("name", "匂いセンサファームウェア"),
        "version": manifest.get("version", "generated"),
        "new_install_prompt_erase": manifest.get("new_install_prompt_erase", True),
    }


def sync_binary_files_to_webflasher(build_dir: Path, parts: list[FlashPart]) -> None:
    """Copy Arduino build outputs to WebFlasher/firmware/."""
    WEBFLASHER_BIN_DIR.mkdir(parents=True, exist_ok=True)

    expected_files = {part.target_name for part in parts}
    for existing in WEBFLASHER_BIN_DIR.glob("*.bin"):
        if existing.name not in expected_files:
            existing.unlink()

    for part in parts:
        source_path = build_dir / part.source_name
        if not source_path.exists():
            raise FileNotFoundError(f"Missing build output: {source_path}")
        shutil.copy2(source_path, WEBFLASHER_BIN_DIR / part.target_name)


def write_flash_config(metadata: dict[str, object], chip_family: str, options: dict[str, str], parts: list[FlashPart]) -> None:
    config = {
        "name": metadata["name"],
        "version": metadata["version"],
        "chipFamily": chip_family,
        "flashMode": options.get("flash-mode", "dio"),
        "flashFreq": options.get("flash-freq", "40m"),
        "flashSize": options.get("flash-size", "4MB"),
        "compress": True,
        "files": [
            {
                "path": part.relative_path,
                "address": part.address,
                "source": part.source_name,
            }
            for part in parts
        ],
    }
    WEBFLASHER_FLASH_CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_manifest_from_flash_config() -> None:
    """Generate docs/firmware/manifest.json from WebFlasher/flash_config.json."""
    if not WEBFLASHER_FLASH_CONFIG_PATH.exists():
        raise FileNotFoundError(f"Run 'build' first: {WEBFLASHER_FLASH_CONFIG_PATH}")
    config = json.loads(WEBFLASHER_FLASH_CONFIG_PATH.read_text(encoding="utf-8"))

    meta = load_manifest_metadata()
    manifest = {
        "name": config.get("name", meta["name"]),
        "version": config.get("version", meta["version"]),
        "new_install_prompt_erase": meta["new_install_prompt_erase"],
        "builds": [
            {
                "chipFamily": config.get("chipFamily", "ESP32"),
                "parts": [
                    {
                        "path": f["path"],
                        "offset": f["address"],
                    }
                    for f in config.get("files", [])
                ],
            }
        ],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_build() -> None:
    """Arduino build outputs -> WebFlasher/"""
    build_dir = find_build_dir()
    options, parts = parse_flash_args(build_dir)
    chip_family = detect_chip_family(build_dir)
    metadata = load_manifest_metadata()

    write_flash_config(metadata, chip_family, options, parts)
    sync_binary_files_to_webflasher(build_dir, parts)

    print(f"Generated {WEBFLASHER_FLASH_CONFIG_PATH.relative_to(REPO_ROOT)}")
    print(f"Synced firmware binaries from {build_dir.relative_to(REPO_ROOT)}")
    print(f"  -> {WEBFLASHER_BIN_DIR.relative_to(REPO_ROOT)}")


def cmd_deploy() -> None:
    """WebFlasher/ -> docs/firmware/"""
    deploy_to_docs()
    write_manifest_from_flash_config()

    print(f"Deployed WebFlasher sources to {DOCS_FIRMWARE_ROOT.relative_to(REPO_ROOT)}")
    print(f"Updated {FLASH_CONFIG_PATH.relative_to(REPO_ROOT)}")
    print(f"Updated {MANIFEST_PATH.relative_to(REPO_ROOT)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync firmware assets")
    parser.add_argument(
        "command",
        nargs="?",
        choices=["build", "deploy"],
        help="build: Arduino->WebFlasher/  deploy: WebFlasher/->docs/firmware/  (omit to run both)",
    )
    args = parser.parse_args()

    if args.command == "build":
        cmd_build()
    elif args.command == "deploy":
        cmd_deploy()
    else:
        cmd_build()
        cmd_deploy()


if __name__ == "__main__":
    main()