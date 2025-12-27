#!/bin/bash
# Setup script for Discord Notetaker Bot

echo "🎙️ Discord Notetaker Bot Setup"
echo "================================"
echo ""

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8+ first."
    exit 1
fi

echo "✓ Python 3 found: $(python3 --version)"
echo ""

# Create virtual environment
echo "📦 Creating virtual environment..."
python3 -m venv venv

if [ $? -ne 0 ]; then
    echo "❌ Failed to create virtual environment"
    exit 1
fi

echo "✓ Virtual environment created"
echo ""

# Activate virtual environment and install dependencies
echo "📥 Installing dependencies (this may take a few minutes)..."
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies"
    exit 1
fi

echo ""
echo "✓ Dependencies installed successfully!"
echo ""

# Check if .env file exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file from template..."
    cp env.example .env
    echo "✓ .env file created"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env file and add your Discord bot token!"
    echo "   Get your token from: https://discord.com/developers/applications"
    echo ""
else
    echo "✓ .env file already exists"
    echo ""
fi

# Check FFmpeg
echo "🔍 Checking for FFmpeg..."
if command -v ffmpeg &> /dev/null; then
    echo "✓ FFmpeg found: $(ffmpeg -version | head -n 1)"
else
    echo "⚠️  FFmpeg not found. Please install it:"
    echo "   macOS: brew install ffmpeg"
    echo "   Linux: sudo apt-get install ffmpeg"
    echo ""
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Edit .env file and add your DISCORD_BOT_TOKEN"
echo "2. Make sure Ollama is running: ollama serve"
echo "3. Run the bot: source venv/bin/activate && python bot.py"
echo ""

