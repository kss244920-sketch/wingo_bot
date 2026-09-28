#!/bin/bash
systemctl --user restart wingo-bot.service
echo "✅ WinGo AI Predictor Service has been STARTED/RESTARTED via systemd!"
echo "📄 Logs check karne ke liye: journalctl --user -u wingo-bot -f  YA  tail -f /home/piyush/wingo_bot/bot.log"
