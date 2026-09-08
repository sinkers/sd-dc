#!/bin/bash
# Run this on the VM after Ubuntu is installed
set -euo pipefail

echo "=== Provisioning FreeCAD MCP VM ==="

# Update system
echo "[1/6] Updating packages..."
sudo apt-get update && sudo apt-get upgrade -y

# Install dependencies
echo "[2/6] Installing dependencies..."
sudo apt-get install -y \
    xvfb \
    git \
    python3-pip \
    python3-venv \
    curl \
    wget \
    software-properties-common \
    libgl1-mesa-glx \
    libglib2.0-0 \
    net-tools

# Install FreeCAD
echo "[3/6] Installing FreeCAD..."
sudo add-apt-repository -y ppa:freecad-maintainers/freecad-stable
sudo apt-get update
sudo apt-get install -y freecad

# Install FreeCAD MCP add-on
echo "[4/6] Installing FreeCAD MCP add-on..."
FREECAD_MOD_DIR="$HOME/.local/share/FreeCAD/Mod"
mkdir -p "$FREECAD_MOD_DIR"
if [ -d "$FREECAD_MOD_DIR/FreeCADMCP" ]; then
    cd "$FREECAD_MOD_DIR/FreeCADMCP" && git pull
else
    git clone https://github.com/mcp-mirror/aigdat_FreeCAD-MCP.git "$FREECAD_MOD_DIR/FreeCADMCP"
fi

# Configure MCP RPC server to bind to all interfaces
echo "[5/6] Configuring RPC server..."
# Patch the RPC server to listen on 0.0.0.0 instead of localhost
INIT_FILE="$FREECAD_MOD_DIR/FreeCADMCP/InitGui.py"
if [ -f "$INIT_FILE" ]; then
    sed -i 's/localhost/0.0.0.0/g' "$INIT_FILE"
    sed -i 's/127\.0\.0\.1/0.0.0.0/g' "$INIT_FILE"
fi

# Also patch any other server files
find "$FREECAD_MOD_DIR/FreeCADMCP" -name "*.py" -exec grep -l "127.0.0.1\|localhost" {} \; | while read f; do
    sed -i 's/127\.0\.0\.1/0.0.0.0/g' "$f"
    sed -i 's/localhost/0.0.0.0/g' "$f"
done

# Create systemd service for headless FreeCAD
echo "[6/6] Creating systemd service..."
sudo tee /etc/systemd/system/freecad-mcp.service > /dev/null << 'EOF'
[Unit]
Description=FreeCAD MCP Server (headless)
After=network.target

[Service]
Type=simple
User=freecad
Environment=DISPLAY=:99
ExecStartPre=/usr/bin/Xvfb :99 -screen 0 1920x1080x24 &
ExecStart=/usr/bin/freecad --no-gui
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Create a separate Xvfb service
sudo tee /etc/systemd/system/xvfb.service > /dev/null << 'EOF'
[Unit]
Description=X Virtual Frame Buffer
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/Xvfb :99 -screen 0 1920x1080x24
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Update FreeCAD service to depend on Xvfb
sudo tee /etc/systemd/system/freecad-mcp.service > /dev/null << 'EOF'
[Unit]
Description=FreeCAD MCP Server (headless)
After=network.target xvfb.service
Requires=xvfb.service

[Service]
Type=simple
User=freecad
Environment=DISPLAY=:99
ExecStart=/usr/bin/freecadcmd -c "import FreeCAD; exec(open('/home/freecad/.local/share/FreeCAD/Mod/FreeCADMCP/start_server.py').read())"
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Enable services
sudo systemctl daemon-reload
sudo systemctl enable xvfb.service
sudo systemctl enable freecad-mcp.service

# Open firewall for RPC
sudo ufw allow 9875/tcp 2>/dev/null || true

echo ""
echo "=== Provisioning Complete ==="
echo "Start services with:"
echo "  sudo systemctl start xvfb"
echo "  sudo systemctl start freecad-mcp"
echo ""
echo "Verify RPC server:"
echo "  curl http://localhost:9875"
