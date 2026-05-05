# S2S Test（Speech-to-Speech 即時語音問答系統）

以 Google Gemini Multimodal Live API 為核心的語音問答系統，透過 FastAPI proxy 保護 API Key，並結合 Supabase pgvector 實現 RAG（檢索增強生成）。

## 架構說明

```
Browser (index.html) ◀── WSS ──▶ server.py (FastAPI / Render) ◀── WSS ──▶ Gemini Live API
                                          │
                               on toolCall│
                                   ┌──────┴──────┐
                                   ▼             ▼
                             OpenAI API      Supabase
                             embeddings      pgvector
```

- **Frontend (`index.html`)**: 單一 HTML 檔，click-to-toggle 錄音介面，透過 AudioWorkletNode 擷取 16kHz PCM 音訊。
- **Backend (`server.py`)**: FastAPI WebSocket proxy，攔截 Gemini 的 `toolCall` 並查詢 FAQ 資料庫，其餘訊息雙向透傳。
- **資料庫**: Supabase Postgres + pgvector，儲存 FAQ 向量。

## 環境變數

在根目錄建立 `.env`（本地）或在 Render 環境設定（部署）：

```
GEMINI_API_KEY=...
OPENAI_API_KEY=...
SUPABASE_DB_URL=postgresql://postgres.<project>:<password>@aws-0-ap-southeast-1.pooler.supabase.com:6543/postgres
```

> **注意**：`SUPABASE_DB_URL` 必須使用 **port 6543**（Transaction Pooler）。server.py 設定了 `statement_cache_size=0`，Session Pooler（port 5432）不相容。

## 本地端開發

```bash
# 安裝依賴
pip install -r requirements.txt

# 啟動 FastAPI server（Terminal 1）
uvicorn server:app --reload

# 開啟前端（Terminal 2，或直接用 http://localhost:8080）
python -m http.server 8080
```

在 `index.html` 第 32 行將 `BACKEND_WS_URL` 改為本地位址：
```javascript
const BACKEND_WS_URL = "ws://localhost:8000/ws";
```

## 部署到 Render

1. 將 `GEMINI_API_KEY`、`OPENAI_API_KEY`、`SUPABASE_DB_URL` 設定為 Render 環境變數。
2. Start command：`uvicorn server:app --host 0.0.0.0 --port 10000`
3. 部署完成後，將 `index.html` 的 `BACKEND_WS_URL` 改回 Render 網址：
   ```javascript
   const BACKEND_WS_URL = "wss://<your-service>.onrender.com/ws";
   ```
4. `index.html` 直接雙擊在瀏覽器開啟，或透過任意 HTTP server serve。

> **Render 免費版冷啟動**：超過 15 分鐘無流量會 sleep，第一次連線需等 20–30 秒。

## Supabase 資料表設定

`search_faq()` 查詢的資料表結構：

```sql
create table faq (
  id bigserial primary key,
  question text,
  answer text,         -- server.py 中 select 的欄位，需與實際欄位名稱一致
  embedding vector(1536)
);
```

若欄位名稱不同，修改 `server.py` 中的 SQL 查詢（`select answer` 及 `row["answer"]`）以符合實際欄位名稱。

## 主要修改紀錄

### 多輪對話支援（Multi-turn conversation）

- **舊行為**：`turnComplete` 後 500ms 自動關閉 WebSocket，每次按鈕建立新的 Gemini session，對話記憶消失。
- **新行為**：`turnComplete` 後保持連線，再次按鈕時沿用同一 Gemini session；15 秒無操作才自動斷線（idle timer）。

### 按鈕改為 Click-to-Toggle

- **舊行為**：`mousedown` 開始錄音、`mouseup`/`mouseleave` 停止，`mouseleave` 容易意外觸發；行動裝置 touch + mouse 事件雙重觸發。
- **新行為**：單一 `click` 事件，第一下開始錄音，再按一下停止送出。按鈕有四個狀態：`idle` / `connecting`（disabled）/ `recording` / `waiting`（disabled）/ `ready`。

### AudioWorklet 取代 ScriptProcessorNode

- `ScriptProcessorNode` 已棄用且在主執行緒執行，改為 `AudioWorkletNode`（獨立 audio thread）。
- Worklet 程式碼以 inline Blob 方式載入，不需要額外的 `.js` 檔案。
- `activityStart` 改為等待 `await startMicStreaming()` 完成後才送出，確保 mic 與 Worklet 就緒後才通知 Gemini 開始接收音訊。

### WebSocket Keepalive（防止 Render 切斷閒置連線）

- Server → Gemini：`websockets.connect(..., ping_interval=20, ping_timeout=10)`
- Server → Browser：每 15 秒送一個 `{"type": "keepalive"}` JSON 訊息；Browser 端直接忽略。

### Server 任務生命週期修正

- 舊的 `asyncio.gather` 在一個 task 結束後無法主動取消另一個。
- 改為 `asyncio.wait(FIRST_COMPLETED)` + 明確 `task.cancel()`，任一側（Browser 或 Gemini）斷線時兩個 task 都乾淨結束。
