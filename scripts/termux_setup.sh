#!/usr/bin/env bash
# One-time setup on an Android phone with Termux (from F-Droid). Run inside Termux:
#   pkg install -y git && git clone https://github.com/hnguyen76/actions-tracker.git ~/actions-tracker
#   bash ~/actions-tracker/scripts/termux_setup.sh
set -e
REPO="$HOME/actions-tracker"
cd "$REPO"

echo "== 1/5 Cai Python va cac goi can thiet (vai phut) =="
pkg update -y && pkg upgrade -y
pkg install -y python git cronie termux-services
if ! python -c "import pandas" 2>/dev/null; then
  pkg install -y python-pandas 2>/dev/null \
    || { pkg install -y tur-repo && pkg install -y python-pandas; } \
    || pip install pandas
fi
python -c "import requests" 2>/dev/null || pip install requests
python -c "import openpyxl" 2>/dev/null || pip install openpyxl
python -c "import pandas, requests, openpyxl; print('Python OK, pandas', pandas.__version__)"

echo "== 2/5 Telegram (bao truoc tran 15 phut, keo len >= 5 picks) =="
# line/scores now come from ESPN for free; The Odds API key is no longer needed
if [ ! -s .telegram_bot_token ]; then
  read -rsp "Dan token cua bot Telegram (tu BotFather, khong hien len man hinh) roi bam Enter: " tok; echo
  printf '%s' "$tok" > .telegram_bot_token
fi
if [ ! -s .telegram_chat_id ]; then
  read -rp "Telegram chat id (so tren may tinh: file .telegram_chat_id): " chat
  printf '%s' "$chat" > .telegram_chat_id
fi
chmod 600 .telegram_bot_token .telegram_chat_id 2>/dev/null || true
echo "Da luu vao .telegram_bot_token / .telegram_chat_id (khong bao gio duoc commit)."

echo "== 3/5 Tai khoan GitHub de day du lieu =="
git config --global credential.helper store
if [ -z "$(git config --global user.name)" ]; then
  read -rp "GitHub username: " gh_user
  git config --global user.name "$gh_user"
  git config --global user.email "${gh_user}@users.noreply.github.com"
fi
git config --global pull.rebase true

echo "== 4/5 Chay thu lan dau =="
echo "Khi git hoi: Username = GitHub username, Password = token (fine-grained, chi repo actions-tracker, Contents: Read and write)."
bash scripts/auto_update.sh update

echo "== 5/5 Hen gio (gio cua dien thoai), giong lich tren may tinh =="
# sync: every 5 min 24/7 (no data scan); update: every 15 min 11:00-23:00 (+ Sunday from 09:00);
# alert: every 5 min, same hours; live: every 5 min 09:02-23:57
J="bash $REPO/scripts/auto_update.sh"
L=">> $HOME/actions-auto.log 2>&1"
( crontab -l 2>/dev/null | grep -v auto_update.sh || true
  echo "2-59/5 * * * * $J sync $L"
  echo "*/15 11-22 * * * $J update $L"
  echo "0 23 * * * $J update $L"
  echo "*/15 9-10 * * 0 $J update $L"
  echo "1-59/5 11-22 * * * $J alert $L"
  echo "1-59/5 9-10 * * 0 $J alert $L"
  echo "3-59/5 9-23 * * * $J live $L" ) | crontab -
# shellcheck disable=SC1091
source "$PREFIX/etc/profile.d/start-services.sh" 2>/dev/null || true
sv-enable crond || echo "Neu bao loi: dong Termux, mo lai, roi chay: sv-enable crond"
termux-wake-lock || true
# restart the schedule after a phone reboot (needs the Termux:Boot app from F-Droid, opened once)
mkdir -p "$HOME/.termux/boot"
cat > "$HOME/.termux/boot/start-actions.sh" <<'BOOT'
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
. "$PREFIX/etc/profile.d/start-services.sh"
BOOT
chmod +x "$HOME/.termux/boot/start-actions.sh"
crontab -l
echo "Xong. Nho: Cai dat > Pin > Gioi han su dung nen > 'Ung dung khong bao gio ngu' > them Termux."
echo "Xem nhat ky: tail -n 40 ~/actions-auto.log"
