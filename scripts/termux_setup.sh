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

echo "== 2/5 API key The Odds API =="
if [ ! -s .odds_api_key ]; then
  read -rsp "Dan API key The Odds API (khong hien len man hinh) roi bam Enter: " key; echo
  printf '%s' "$key" > .odds_api_key
  chmod 600 .odds_api_key
fi
echo "Da luu key vao .odds_api_key (khong bao gio duoc commit)."

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
bash scripts/auto_update.sh

echo "== 5/5 Hen gio chay moi gio (phut thu 7) =="
( crontab -l 2>/dev/null | grep -v auto_update.sh || true
  echo "7 * * * * bash $REPO/scripts/auto_update.sh >> $HOME/actions-auto.log 2>&1" ) | crontab -
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
