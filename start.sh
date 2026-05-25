#!/bin/bash
# Start the Ponca City Beauty College Document Signing System

cd "$(dirname "$0")"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

echo "Activating virtual environment..."
source venv/bin/activate

echo "Installing dependencies..."
pip install -q flask

echo ""
echo "=========================================="
echo "  PCBC Document Signing System"
echo "=========================================="
echo "  Opening at: http://localhost:5000"
echo "  Admin:      admin / ponca2024"
echo "=========================================="
echo ""

python app.py
