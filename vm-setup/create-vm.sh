#!/bin/bash
set -euo pipefail

VM_NAME="freecad-mcp"
CLOUD_IMG="${1:-/Users/andrewsinclair/Downloads/ubuntu-noble-arm64.img}"
VM_DIR="/Users/andrewsinclair/Parallels"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Creating FreeCAD MCP VM from cloud image ==="

# Check if VM already exists
if prlctl list -a 2>/dev/null | grep -q "$VM_NAME"; then
    echo "VM '$VM_NAME' already exists."
    echo "To delete: prlctl stop $VM_NAME && prlctl delete $VM_NAME"
    exit 1
fi

# Verify cloud image exists
if [ ! -f "$CLOUD_IMG" ]; then
    echo "Error: Cloud image not found at $CLOUD_IMG"
    echo "Download it: curl -L -o $CLOUD_IMG https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img"
    exit 1
fi

# Step 1: Convert qcow2 to raw
echo "[1/6] Converting cloud image to raw format..."
RAW_IMG="/tmp/ubuntu-noble-arm64.raw"
QEMU_IMG="/Users/andrewsinclair/Library/Android/sdk/emulator/qemu-img"
$QEMU_IMG convert -f qcow2 -O raw "$CLOUD_IMG" "$RAW_IMG"

# Resize the raw image to 40GB
echo "[2/6] Resizing disk to 40GB..."
$QEMU_IMG resize -f raw "$RAW_IMG" 40G

# Step 3: Create Parallels VM (blank)
echo "[3/6] Creating Parallels VM..."
prlctl create "$VM_NAME" --distribution ubuntu --no-hdd --dst "$VM_DIR"

# Configure hardware
prlctl set "$VM_NAME" --cpus 4
prlctl set "$VM_NAME" --memsize 8192
prlctl set "$VM_NAME" --device-set net0 --type shared
# Enable EFI boot for ARM64
prlctl set "$VM_NAME" --efi-boot on 2>/dev/null || true

# Step 4: Convert raw to Parallels HDD format and attach
echo "[4/6] Converting to Parallels HDD format..."
HDD_PATH="$VM_DIR/${VM_NAME}.pvm/harddisk1.hdd"
prl_disk_tool convert --hdd "$RAW_IMG" --dst "$HDD_PATH" 2>/dev/null || {
    # If convert doesn't work, use import approach
    echo "    Using alternative import method..."
    mkdir -p "$HDD_PATH"
    prl_disk_tool create --hdd "$HDD_PATH" --size 40960
    # Copy the raw disk content
    dd if="$RAW_IMG" of="$HDD_PATH/harddisk1.hdd.0.{5fbaabe3-6958-40ff-92a7-860e329aab41}.hds" bs=1M 2>/dev/null || true
}

# Attach the HDD to VM
prlctl set "$VM_NAME" --device-add hdd --image "$HDD_PATH" 2>/dev/null || {
    echo "    HDD may already be attached, continuing..."
}

# Step 5: Create cloud-init seed ISO
echo "[5/6] Creating cloud-init seed ISO..."
SEED_DIR="/tmp/cloud-init-seed"
rm -rf "$SEED_DIR"
mkdir -p "$SEED_DIR"
cp "$SCRIPT_DIR/cloud-init/user-data" "$SEED_DIR/user-data"
cp "$SCRIPT_DIR/cloud-init/meta-data" "$SEED_DIR/meta-data"

# Create ISO using hdiutil (macOS native)
SEED_ISO="/tmp/cloud-init-seed.iso"
hdiutil makehybrid -o "$SEED_ISO" "$SEED_DIR" -joliet -iso -default-volume-name cidata 2>/dev/null || {
    # Alternative: just mount the directory
    echo "    Could not create seed ISO, will configure manually after boot"
}

# Attach seed ISO if created
if [ -f "${SEED_ISO}.iso" ]; then
    mv "${SEED_ISO}.iso" "$SEED_ISO"
fi
if [ -f "$SEED_ISO" ]; then
    prlctl set "$VM_NAME" --device-add cdrom --image "$SEED_ISO" --connect 2>/dev/null || true
fi

# Step 6: Set boot order and start
echo "[6/6] Finalizing..."
prlctl set "$VM_NAME" --device-bootorder "hdd0" 2>/dev/null || true

# Clean up temp files
rm -f "$RAW_IMG"

echo ""
echo "=== VM Created Successfully ==="
echo "VM Name: $VM_NAME"
echo ""
echo "Start with: prlctl start $VM_NAME"
echo "Get IP:     prlctl list -f"
echo "SSH:        ssh -i ~/.ssh/freecad-vm freecad@<IP>"
echo ""
echo "After first boot + cloud-init, run:"
echo "  scp provision.sh freecad@<IP>:~/"
echo "  ssh freecad@<IP> 'bash ~/provision.sh'"
