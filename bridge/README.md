# Scent Bridge

ローカル PC 上で動作する Scent Viewer と AI エージェント間のゲートウェイです。

## 機能

- **WebSocket / HTTP エンドポイント**：Viewer からのイベント受信
- **Ollama 連携**：ローカル LLM による軽量分析
- **コマンド実行**：AI エージェントから Viewer へのコマンド送信
- **イベントキュー**：イベント履歴の記録と管理
- **マルチプレクシング**：複数 Viewer の同時接続サポート

## セットアップ

### 1. Python 環境構築

```bash
cd bridge
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # macOS/Linux
```

### 2. 依存パッケージインストール

```bash
pip install -r requirements.txt
```

### 3. 環境変数設定

```bash
cp .env.example .env
# .env を編集
```

### 4. Ollama 起動（別ターミナル）

```bash
ollama serve
ollama pull mistral  # または llama2
```

### 5. ブリッジ起動

```bash
python main.py
```

ブリッジは `http://127.0.0.1:8001` で起動します。

## API エンドポイント

### HTTP

bridge は単なるイベントキューだけでなく、接続中 Viewer から同期された localStorage ベースのセッション状態も保持します。
そのため `/sessions` と `/sessions/{session_id}/download` は、現在 bridge に状態同期している Viewer origin の内容を返します。

例:
- `http://localhost:8000/viewer/` が接続中なら localhost 側 localStorage のセッションを返す
- `https://ksasao.github.io/Scent/viewer/` が接続中なら GitHub Pages 側 localStorage のセッションを返す

**ヘルスチェック**
```
GET /health
```

`/health` には bridge の基本状態に加えて、現在のデバイス ID、Viewer からのデータ受信状況、現在のセッション同期元 origin (`viewer_state_origin`) も含まれます。

**Viewer 状態同期**
```
POST /viewer-state
Content-Type: application/json

{
  "origin": "http://localhost:8000",
  "page_url": "http://localhost:8000/viewer/",
  "sessions": [
    {
      "id": "abc123",
      "name": "sample",
      "startIso": "2026-05-09T10:00:00Z",
      "endIso": "2026-05-09T10:01:00Z",
      "sensorId": "01B55913",
      "records": []
    }
  ]
}
```

**イベント受信**
```
POST /event
Content-Type: application/json

{
  "type": "data_record",
  "data": {
    "session_id": "abc123",
    "ch": 5,
    "value": 1.23
  }
}
```

**イベント履歴取得**
```
GET /events?skip=0&limit=100
```

**セッション一覧取得**
```
GET /sessions
```

現在 bridge に同期されている Viewer のセッション一覧を返します。

**セッション ZIP ダウンロード**
```
GET /sessions/{session_id}/download
```

指定 `session_id` を、現在同期されている Viewer の localStorage セッション内容から ZIP 化して返します。

**保留中コマンド取得**
```
GET /commands/pending
```

**コマンド実行報告**
```
POST /commands/execute/{command_id}
{
  "result": {...}
}
```

**AI エージェント問い合わせ**
```
POST /agent/query
Content-Type: application/json

{
  "prompt": "現在デバイスからデータを受信中かどうかを確認して"
}
```

受信中判定の問い合わせは bridge がローカルで即時回答します。その他の問い合わせは Ollama にフォールバックします。

### WebSocket

**Viewer 接続**
```
ws://127.0.0.1:8001/ws/viewer
```

イベント送信例：
```json
{
  "type": "event",
  "event_type": "data_record",
  "data": {
    "session_id": "abc123",
    "ch": 5,
    "value": 1.23
  }
}
```

コマンド実行結果報告例：
```json
{
  "type": "command_result",
  "command_id": "cmd-1234567890",
  "result": {
    "success": true,
    "file": "session_abc123.zip"
  }
}
```

`/agent/query` の応答例：
```json
{
  "prompt": "現在デバイスからデータを受信中かどうかを確認して",
  "handled_locally": true,
  "result": {
    "answer": "はい。現在デバイスからデータを受信中です。",
    "details": "data received within last 15 seconds; sensor_id=0x12345678; last_data_age=2.31s"
  }
}
```

## ディレクトリ構成

```
bridge/
├── main.py              # エントリーポイント
├── server.py            # FastAPI サーバー実装
├── config.py            # 設定
├── events.py            # イベント定義
├── commands.py          # コマンド定義
├── ai.py                # AI 連携（Ollama / 外部 API）
├── requirements.txt     # 依存パッケージ
├── .env.example         # 環境変数テンプレート
├── logs/                # ログファイル出力先
└── README.md            # このファイル
```

## ロギング

ログは `logs/bridge.log` に出力されます。

## 拡張例

### 外部 AI API 連携

`ai.py` の `AIRouter` クラスを拡張：

```python
async def route_event(self, event: Event) -> dict:
    if event.type == EventType.SESSION_ENDED:
        # 重いイベント → OpenAI に送信
        response = await call_openai(event)
        return response
```

### カスタムコマンド処理

`commands.py` に新しいコマンド型を追加：

```python
class CommandType(str, Enum):
    CUSTOM_ACTION = "custom_action"
```

`server.py` で処理：

```python
@app.post("/commands/custom")
async def execute_custom_command(payload: dict):
    # カスタムロジック
    pass
```

## トラブルシューティング

**Ollama に接続できない**
- Ollama が `ollama serve` で起動しているか確認
- ポート 11434 が開いているか確認

**CORS エラー**
- `config.py` の `ALLOWED_ORIGINS` を GitHub Pages URL に合わせる

**イベント処理が遅い**
- `ai.py` でタイムアウト値を調整
- イベント型別の処理を最適化

## ライセンス

Apache License 2.0

## MCP サーバー（案1: 別プロセスアダプタ）

既存 bridge をそのまま利用し、MCP は別プロセス `mcp_server.py` で提供します。

### 起動

```bash
cd bridge
python mcp_server.py
```

上記のデフォルトは HTTP トランスポート (`streamable-http`) で `127.0.0.1:8002` にバインドします。

明示的に指定する場合:

```bash
python mcp_server.py --transport streamable-http --host 127.0.0.1 --port 8002
```

VS Code 連携など stdio トランスポートで起動する場合:

```bash
python mcp_server.py --transport stdio
```

デフォルトでは `http://127.0.0.1:8001` の bridge に接続します。必要に応じて環境変数を指定できます。

```bash
set SCENT_BRIDGE_URL=http://127.0.0.1:8001
set SCENT_COMMAND_WAIT_SECONDS=12
set SCENT_MCP_DOWNLOAD_DIR=C:\path\to\downloads
set SCENT_MCP_TRANSPORT=streamable-http
set SCENT_MCP_HOST=127.0.0.1
set SCENT_MCP_PORT=8002
```

### 提供ツール

- `bridge_health`
- `sessions_list`
- `device_connect`
- `device_disconnect`
- `session_start`
- `session_stop`
- `device_id_get_live`
- `session_download`

`device_id_get_live` はキャッシュ値ではなく、Viewer へ `query_device_id` コマンドを送り、都度取得結果を待って返します。
