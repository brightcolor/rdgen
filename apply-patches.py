#!/usr/bin/env python3
"""
Patcht die rdgen-Generator-Workflows fuer den Standalone-Betrieb.

Aenderungen an generator-windows.yml und generator-linux.yml:
  1. workflow_call-Trigger hinzufuegen (damit check-and-build.yml sie aufrufen kann)
  2. secrets: inherit zum setup-Job hinzufuegen (damit Secrets an fetch-encrypted-secrets.yml weitergegeben werden)
  3. permissions: contents: write hinzufuegen (fuer spaetere Release-Schritte)
  4. Artifact-Upload-Schritt einfuegen (vor den rdgen/api-Upload-Schritten)

Ausfuehren im Wurzelverzeichnis des Repos:
  python apply-patches.py
"""

import sys
import re
from pathlib import Path


# ─────────────────────────────────────────────────────────────────
# workflow_call-Block, der in den on:-Abschnitt eingefuegt wird
# ─────────────────────────────────────────────────────────────────
WORKFLOW_CALL_BLOCK = """\
  workflow_call:
    inputs:
      version:
        description: 'Version to build'
        required: true
        type: string
      zip_url:
        description: 'Ignored in standalone mode'
        required: false
        type: string
        default: '{"url":"none","file":"none"}'
"""

# ─────────────────────────────────────────────────────────────────
# Artifact-Upload-Schritt fuer Windows (exe + msi)
# ─────────────────────────────────────────────────────────────────
WINDOWS_UPLOAD_STEP = """\
      - name: Artifacts fuer GitHub Release hochladen (Windows)
        uses: actions/upload-artifact@v4
        with:
          name: windows-client-${{ env.VERSION }}
          path: |
            ./SignOutput/${{ env.filename }}.exe
            ./SignOutput/${{ env.filename }}.msi
          retention-days: 7
          if-no-files-found: warn

"""

# ─────────────────────────────────────────────────────────────────
# Artifact-Upload-Schritt fuer Linux (deb + rpm + zst)
# ─────────────────────────────────────────────────────────────────
LINUX_UPLOAD_STEP = """\
      - name: Artifacts fuer GitHub Release hochladen (Linux)
        uses: actions/upload-artifact@v4
        with:
          name: linux-client-${{ env.VERSION }}-${{ matrix.job.arch }}
          path: |
            ./output/${{ env.filename }}-${{ matrix.job.arch }}.deb
            ./output/${{ env.filename }}-${{ matrix.job.arch }}.rpm
            ./output/${{ env.filename }}-suse-${{ matrix.job.arch }}.rpm
            ./output/${{ env.filename }}-${{ matrix.job.arch }}.pkg.tar.zst
          retention-days: 7
          if-no-files-found: warn

"""

RDGEN_SEND_MARKER   = "      - name: send file to rdgen server"
SETUP_JOB_USES      = "    uses: ./.github/workflows/fetch-encrypted-secrets.yml"
SETUP_SECRETS_LINE  = "    secrets: inherit"


# ─────────────────────────────────────────────────────────────────
# Patch-Funktionen
# ─────────────────────────────────────────────────────────────────

def add_workflow_call(content: str) -> str:
    """Fuegt workflow_call-Trigger in den on:-Block ein."""
    if "workflow_call:" in content:
        print("  → workflow_call: bereits vorhanden")
        return content

    # Vor dem env:-Block einfuegen (nach den workflow_dispatch-Inputs)
    pattern = r'(\n\nenv:\n)'
    replacement = '\n\n' + WORKFLOW_CALL_BLOCK + '\nenv:\n'
    new_content, count = re.subn(pattern, replacement, content, count=1)

    if count:
        print("  → workflow_call: hinzugefuegt")
    else:
        print("  Warnung: Konnte workflow_call: nicht einfuegen – bitte manuell pruefen")
    return new_content


def add_permissions(content: str) -> str:
    """Fuegt permissions: contents: write auf Workflow-Ebene ein."""
    if "permissions:" in content:
        print("  → permissions: bereits vorhanden")
        return content

    pattern = r'(\n\nenv:\n)'
    replacement = '\n\npermissions:\n  contents: write\n\nenv:\n'
    new_content, count = re.subn(pattern, replacement, content, count=1)

    if count:
        print("  → permissions: contents: write hinzugefuegt")
    else:
        print("  Warnung: Konnte permissions: nicht einfuegen")
    return new_content


def add_secrets_inherit(content: str) -> str:
    """Fuegt 'secrets: inherit' zum setup-Job hinzu."""
    if SETUP_SECRETS_LINE in content:
        print("  → secrets: inherit bereits vorhanden")
        return content

    # Nach "uses: ./.github/workflows/fetch-encrypted-secrets.yml" einfuegen
    old = SETUP_JOB_USES + "\n    with:"
    new = SETUP_JOB_USES + "\n" + SETUP_SECRETS_LINE + "\n    with:"

    if old in content:
        content = content.replace(old, new, 1)
        print("  → secrets: inherit zum setup-Job hinzugefuegt")
    else:
        print("  Warnung: setup-Job-Marker nicht gefunden – secrets: inherit bitte manuell ergaenzen")
    return content


def insert_upload_step(content: str, upload_step: str, label: str) -> str:
    """Fuegt den Artifact-Upload-Schritt vor dem rdgen-Send-Marker ein."""
    if "Artifacts fuer GitHub Release hochladen" in content:
        print(f"  → {label}-Upload-Schritt bereits vorhanden")
        return content

    if RDGEN_SEND_MARKER in content:
        content = content.replace(RDGEN_SEND_MARKER,
                                  upload_step + RDGEN_SEND_MARKER, 1)
        print(f"  → {label}-Artifact-Upload-Schritt eingefuegt")
    else:
        print(f"  Warnung: Marker '{RDGEN_SEND_MARKER.strip()}' nicht gefunden")
        print(f"    Bitte den folgenden Schritt manuell vor 'send file to rdgen server' einfuegen:")
        print()
        for line in upload_step.splitlines():
            print(f"    {line}")
    return content


def patch_file(path: Path, patch_fn) -> bool:
    if not path.exists():
        print(f"  Datei nicht gefunden: {path}")
        return False

    print(f"\nPatche {path.name} ...")
    original = path.read_text(encoding="utf-8")

    patched = patch_fn(original)

    if patched == original:
        print(f"  → Keine Aenderungen noetig (bereits aktuell)")
        return True

    backup = path.with_suffix(".yml.bak")
    backup.write_text(original, encoding="utf-8")
    print(f"  → Backup: {backup.name}")

    path.write_text(patched, encoding="utf-8")
    print(f"  Gespeichert: {path.name}")
    return True


# ─────────────────────────────────────────────────────────────────
# Workflow-spezifische Patch-Funktionen
# ─────────────────────────────────────────────────────────────────

def patch_windows(content: str) -> str:
    content = add_workflow_call(content)
    content = add_permissions(content)
    content = add_secrets_inherit(content)
    content = insert_upload_step(content, WINDOWS_UPLOAD_STEP, "Windows")
    return content


def patch_linux(content: str) -> str:
    content = add_workflow_call(content)
    content = add_permissions(content)
    content = add_secrets_inherit(content)
    content = insert_upload_step(content, LINUX_UPLOAD_STEP, "Linux")
    return content


# ─────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────

def main():
    workflows = Path(".github/workflows")
    if not workflows.exists():
        print("Fehler: Kein .github/workflows Verzeichnis gefunden.")
        print("Stelle sicher, dass dieses Skript im Wurzelverzeichnis des Repos ausgefuehrt wird.")
        sys.exit(1)

    print("=" * 60)
    print(" rdgen Standalone-Patches")
    print("=" * 60)

    ok_w = patch_file(workflows / "generator-windows.yml", patch_windows)
    ok_l = patch_file(workflows / "generator-linux.yml",  patch_linux)

    print()
    print("=" * 60)
    if ok_w and ok_l:
        print(" Alle Patches erfolgreich angewendet!")
    else:
        print(" Einige Patches konnten nicht angewendet werden.")
        print(" Bitte die Ausgabe pruefen und ggf. manuell anpassen.")
        sys.exit(1)
    print("=" * 60)


if __name__ == "__main__":
    main()
