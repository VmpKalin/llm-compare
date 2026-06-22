#!/usr/bin/env bash
# =============================================================================
# setup_vm.sh — prepare a clean Ubuntu + NVIDIA GPU box (e.g. RunPod RTX 5090)
# for the LLM benchmark. Run once after SSHing into the fresh VM.
#
#   chmod +x setup_vm.sh && ./setup_vm.sh
#
# Assumes: Ubuntu 22.04/24.04, NVIDIA driver already present (true on RunPod
# GPU images). Verify with `nvidia-smi` before running.
# =============================================================================
set -euo pipefail

echo ">> 0/5  Checking GPU is visible..."
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "!! nvidia-smi not found. This box has no GPU driver. Stop and pick a GPU image."
  exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo ">> 1/5  System packages..."
export DEBIAN_FRONTEND=noninteractive
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv git curl >/dev/null

echo ">> 2/5  Installing Ollama..."
if ! command -v ollama >/dev/null 2>&1; then
  curl -fsSL https://ollama.com/install.sh | sh
fi

echo ">> 3/5  Starting Ollama server (background)..."
# On a VM without systemd user services, just run it detached.
if ! curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
  nohup ollama serve > /tmp/ollama.log 2>&1 &
  sleep 5
fi
# Wait until the API answers.
for i in $(seq 1 20); do
  if curl -s http://localhost:11434/api/tags >/dev/null 2>&1; then
    echo "   Ollama is up."
    break
  fi
  sleep 2
done

echo ">> 4/5  Pulling models (~60GB total, takes a while)..."
# The three chosen local models. Edit this list if you change the lineup.
for m in qwen3:32b gemma3:27b deepseek-r1:32b; do
  echo "   pulling $m ..."
  ollama pull "$m"
done

echo ">> 5/5  Python deps for the benchmark..."
pip3 install --quiet --break-system-packages -r requirements.txt 2>/dev/null \
  || pip3 install --quiet -r requirements.txt

echo ""
echo "============================================================"
echo " Setup done. Models available:"
ollama list
echo ""
echo " Disk free:"
df -h / | tail -1
echo "============================================================"
echo ""
echo " Next steps:"
echo "   cp .env.example .env && nano .env      # paste your ANTHROPIC_API_KEY"
echo "   python3 runner.py --backend ollama --model qwen3:32b       --hw rtx5090"
echo "   python3 runner.py --backend ollama --model gemma3:27b      --hw rtx5090"
echo "   python3 runner.py --backend ollama --model deepseek-r1:32b --hw rtx5090"
echo "   python3 runner.py --backend claude --model claude-haiku-4-5-20251001 --hw api"
echo "   python3 runner.py --backend claude --model claude-sonnet-4-6          --hw api"
echo "   python3 evaluate.py"
echo "   python3 report.py        # then download report.html"
echo ""
echo " TIP: keep an eye on VRAM while a model runs:  watch -n1 nvidia-smi"
echo " TIP: free VRAM between models:  ollama stop <model>   (or it auto-unloads)"
