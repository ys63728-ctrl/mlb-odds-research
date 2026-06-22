# クラウド常駐デプロイ手順（Railway）

このBOTを24時間動かすための設定メモ。PCの電源・スリープと無関係に動き続ける。

## 前提
- GitHub にこのリポジトリを push 済み
- Railway アカウント（https://railway.app/ ）

## 手順
1. Railway で **New Project → Deploy from GitHub repo → `mlb-odds-research`** を選ぶ
2. **Variables（環境変数）** に以下を設定（`.env` の値をそのまま）:
   - `DISCORD_TOKEN`
   - `CHANNEL_ID`
   - `ODDS_API_KEY`
   - （任意）`SPORT_KEY`, `DATABASE_URL`
3. **Volume（永続ディスク）** を追加し、マウント先を **`/app/data`** にする
   - これでSQLite（`data/odds_research.db`）がデプロイをまたいで保持される
4. 起動方式は `Procfile`（`worker: python scripts/run_bot.py`）が自動で使われる
5. デプロイ後、Discordに「🤖 監視BOT 起動」が届けば成功

## 重要
- **ローカル(ノートPC)のBOTは必ず止める**。クラウドと同時起動すると通知が二重送信される
  （多重起動防止ロックは同一マシン内のみ有効。別マシン同士は防げない）
- APIキーは増額してもそのまま使える（クラウド側の環境変数に同じ値を入れるだけ）
