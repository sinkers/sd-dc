# FreeCAD VM MCP - Installation Guide

Complete instructions for setting up a headless FreeCAD instance on a Parallels VM with MCP integration for AI agent control.

## Prerequisites

- macOS on Apple Silicon (ARM64)
- Parallels Desktop 26+ installed (`prlctl` available in PATH)
- ~10GB free disk space
- Internet connection for downloads

## Step-by-Step Installation

### 1. Download Ubuntu Cloud Image

```bash
curl -L -o ~/Downloads/ubuntu-noble-arm64.img \
  "https://cloud-images.ubuntu.com/noble/current/noble-server-cloudimg-arm64.img"
```

This is a 590MB pre-installed Ubuntu 24.04 image (much faster than using a live ISO installer).

### 2. Generate SSH Key

```bash
ssh-keygen -t ed25519 -f ~/.ssh/freecad-vm -N "" -C "freecad-vm"
```

### 3. Create Cloud-Init Configuration

Create a directory and two files:

```bash
mkdir -p /tmp/cloud-init-seed
```

**`/tmp/cloud-init-seed/user-data`:**
```yaml
#cloud-config
> **Set a password before using this.** Generate one and paste it in place of
> every `<GENERATED-PASSWORD>` below:
>
> ```bash
> LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24; echo
> ```
>
> This VM authenticates by SSH key; the password is only a console fallback. If
> you do not need console access, set `ssh_pwauth: false` and drop the
> `chpasswd` block entirely.

users:
  - name: freecad
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false
    plain_text_passwd: <GENERATED-PASSWORD>
    ssh_authorized_keys:
      - <PASTE CONTENTS OF ~/.ssh/freecad-vm.pub HERE>

ssh_pwauth: true
password: <GENERATED-PASSWORD>
chpasswd:
  expire: false
  users:
    - name: freecad
      password: <GENERATED-PASSWORD>
      type: text

package_update: true
packages:
  - openssh-server
  - curl
  - git
  - python3-pip
  - python3-venv
  - xvfb
  - net-tools
  - software-properties-common

runcmd:
  - systemctl enable ssh
  - systemctl start ssh
```

**`/tmp/cloud-init-seed/meta-data`:**
```yaml
instance-id: freecad-vm-001
local-hostname: freecad-vm
```

### 4. Create Cloud-Init Seed ISO

```bash
hdiutil makehybrid -o /tmp/seed.iso /tmp/cloud-init-seed \
  -joliet -iso -default-volume-name cidata
```

### 5. Convert Cloud Image to Parallels Format

```bash
# Convert qcow2 → raw
qemu-img convert -f qcow2 -O raw \
  ~/Downloads/ubuntu-noble-arm64.img \
  /tmp/ubuntu-noble-arm64.raw

# Resize to 40GB
qemu-img resize -f raw /tmp/ubuntu-noble-arm64.raw 40G
```

> **Note:** If `qemu-img` is not in PATH, check:
> - `brew install qemu` (recommended)
> - Android SDK: `~/Library/Android/sdk/emulator/qemu-img`

### 6. Create Parallels VM

```bash
# Create VM without disk
prlctl create "freecad-mcp" --distribution ubuntu --no-hdd \
  --dst ~/Parallels

# Configure hardware
prlctl set "freecad-mcp" --cpus 4
prlctl set "freecad-mcp" --memsize 8192
prlctl set "freecad-mcp" --device-set net0 --type shared
```

### 7. Prepare and Attach Disk

```bash
VM_DIR=~/Parallels/freecad-mcp.pvm
mkdir -p "$VM_DIR/harddisk1.hdd"

# Convert raw to Parallels format
qemu-img convert -f raw -O parallels \
  /tmp/ubuntu-noble-arm64.raw \
  "$VM_DIR/harddisk1.hdd/harddisk1.hdd.0.{5fbaabe3-6958-40ff-92a7-860e329aab41}.hds"
```

Create `$VM_DIR/harddisk1.hdd/DiskDescriptor.xml`:
```xml
<?xml version="1.0" encoding="UTF-8"?>
<Parallels_disk_image Version="1.0">
  <Disk_Parameters>
    <Disk_size>83886080</Disk_size>
    <Cylinders>81920</Cylinders>
    <Heads>16</Heads>
    <Sectors>63</Sectors>
    <Padding>0</Padding>
    <Encryption>
      <Engine>{00000000-0000-0000-0000-000000000000}</Engine>
    </Encryption>
    <Miscellaneous>
      <CompatLevel>level2</CompatLevel>
      <Bootable>true</Bootable>
    </Miscellaneous>
  </Disk_Parameters>
  <StorageData>
    <Storage>
      <Start>0</Start>
      <End>83886080</End>
      <Blocksize>2048</Blocksize>
      <Image>
        <GUID>{5fbaabe3-6958-40ff-92a7-860e329aab41}</GUID>
        <Type>Compressed</Type>
        <File>harddisk1.hdd.0.{5fbaabe3-6958-40ff-92a7-860e329aab41}.hds</File>
      </Image>
    </Storage>
  </StorageData>
  <Snapshots>
    <Shot>
      <GUID>{5fbaabe3-6958-40ff-92a7-860e329aab41}</GUID>
      <ParentGUID>{00000000-0000-0000-0000-000000000000}</ParentGUID>
    </Shot>
  </Snapshots>
</Parallels_disk_image>
```

Also create a backup copy:
```bash
cp "$VM_DIR/harddisk1.hdd/DiskDescriptor.xml" \
   "$VM_DIR/harddisk1.hdd/DiskDescriptor.xml.Backup"
```

Attach disk and seed ISO:
```bash
prlctl set "freecad-mcp" --device-add hdd \
  --image "$VM_DIR/harddisk1.hdd"

prlctl set "freecad-mcp" --device-add cdrom \
  --image /tmp/seed.iso --connect
```

### 8. Boot VM and Wait for Cloud-Init

```bash
prlctl start "freecad-mcp"

# Wait 30-45 seconds for boot + cloud-init
sleep 30

# Get IP
prlctl list -f
# Note the IP (typically 10.211.55.x)

# Verify SSH
ssh -i ~/.ssh/freecad-vm freecad@<VM_IP> "echo works"

# Wait for cloud-init to fully complete
ssh -i ~/.ssh/freecad-vm freecad@<VM_IP> "cloud-init status --wait"
```

### 9. Install FreeCAD via Conda

```bash
ssh -i ~/.ssh/freecad-vm freecad@<VM_IP> << 'EOF'
# Install miniforge
curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-aarch64.sh"
bash Miniforge3-Linux-aarch64.sh -b -p $HOME/miniforge3
rm Miniforge3-Linux-aarch64.sh
export PATH="$HOME/miniforge3/bin:$PATH"
echo 'export PATH="$HOME/miniforge3/bin:$PATH"' >> ~/.bashrc

# Install FreeCAD
conda install -y -c conda-forge freecad

# Verify
freecadcmd --version
EOF
```

This takes 5-10 minutes depending on network speed.

### 10. Deploy RPC Server

Copy `freecad_rpc_server.py` to the VM:

```bash
scp -i ~/.ssh/freecad-vm freecad_rpc_server.py freecad@<VM_IP>:~/
```

### 11. Configure Auto-Start Service

```bash
ssh -i ~/.ssh/freecad-vm freecad@<VM_IP> << 'EOF'
# Create startup script
cat > ~/start_freecad_rpc.sh << 'SCRIPT'
#!/bin/bash
export PATH=$HOME/miniforge3/bin:$PATH
export DISPLAY=:99
exec xvfb-run -a freecadcmd -c "exec(open('/home/freecad/freecad_rpc_server.py').read())"
SCRIPT
chmod +x ~/start_freecad_rpc.sh

# Create systemd user service
mkdir -p ~/.config/systemd/user
cat > ~/.config/systemd/user/freecad-rpc.service << 'SVC'
[Unit]
Description=FreeCAD RPC Server
After=network.target

[Service]
Type=simple
ExecStart=/home/freecad/start_freecad_rpc.sh
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
SVC

# Enable lingering + service
sudo loginctl enable-linger freecad
systemctl --user daemon-reload
systemctl --user enable freecad-rpc.service
systemctl --user start freecad-rpc.service
EOF
```

### 12. Verify RPC Server

From the host:

```bash
python3 -c "
import xmlrpc.client
proxy = xmlrpc.client.ServerProxy('http://<VM_IP>:9875/RPC2')
print(proxy.ping())          # → 'pong'
print(proxy.get_version())   # → FreeCAD version dict
print(proxy.list_documents()) # → []
"
```

### 13. Configure MCP Bridge (Optional)

To use via Claude Code's MCP tools, update `~/.claude.json`:

```json
{
  "mcpServers": {
    "freecad": {
      "type": "stdio",
      "command": "uvx",
      "args": ["freecad-mcp", "--host", "<VM_IP>"],
      "env": {}
    }
  }
}
```

Requires: `uvx` (from `uv` tool) and the `freecad-mcp` package.

## Cleanup

```bash
# Remove temp files
rm -f /tmp/ubuntu-noble-arm64.raw /tmp/seed.iso

# To fully remove VM
prlctl stop freecad-mcp
prlctl delete freecad-mcp
rm -f ~/Downloads/ubuntu-noble-arm64.img
```

## Performance Notes

- VM uses ~800MB RAM at idle with FreeCAD loaded
- Complex models (>1000 objects) may need increased memory
- Tessellation for SVG rendering is CPU-bound; large models use tolerance 10-50mm
- STEP export is fast; STL/OBJ export depends on tessellation quality
- The VM auto-starts the RPC server on boot (via systemd user service)

## Supported FreeCAD Modules (Headless)

| Module | Status | Notes |
|--------|--------|-------|
| Part | ✅ Full | Core solid modelling |
| Mesh | ✅ Full | Tessellation, STL/OBJ export |
| Sketcher | ✅ Full | 2D constraints |
| PartDesign | ✅ Full | Feature-based modelling |
| Draft | ✅ Full | 2D drafting |
| Arch | ✅ Full | Architecture/BIM |
| FEM | ✅ Full | Finite element analysis |
| TechDraw | ⚠️ Partial | Page creation works, rendering limited |
| Drawing | ❌ Removed | Deprecated in FreeCAD 1.x |
| FreeCADGui | ❌ N/A | No GUI in headless mode |
