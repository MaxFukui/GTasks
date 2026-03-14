#!/usr/bin/env bash
set -e

VENV_DIR=".venv"

echo "==> Creating virtual environment in $VENV_DIR..."
python3 -m venv "$VENV_DIR"

echo "==> Activating virtual environment..."
source "$VENV_DIR/bin/activate"

echo "==> Installing dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt

echo "==> Installing the app in editable mode..."
pip install -e . -q

echo ""
echo "Setup complete!"
echo ""
echo "To activate the environment in the future, run:"
echo "  source $VENV_DIR/bin/activate"
echo ""
echo "Before running the app, make sure you have:"
echo "  1. Enabled the Google Tasks API at https://console.developers.google.com/"
echo "  2. Downloaded your OAuth credentials as 'client_secrets.json'"
echo "  3. Placed client_secrets.json in ~/.gtask/"
echo "     mkdir -p ~/.gtask && mv client_secrets.json ~/.gtask/"
echo ""
echo "Then run the app with:"
echo "  tasks-tui"
