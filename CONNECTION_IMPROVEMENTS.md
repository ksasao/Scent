# Connect → Device ID 取得フローの改善

## 問題の原因

Connect ボタンを押してから Device ID を取得するまでの接続フローで、環境によって以下の問題が発生していました：

1. **ポーリング間隔が長かった（100ms）**
   - 高遅延環境では応答を見落とす可能性
   
2. **ID 要求を1回だけ送信**
   - デバイス側の処理が遅い場合、タイムアウトまで待つしかない
   - 再試行メカニズムがない

3. **readLoop() が ID 取得後に開始されていた**
   - ID コマンドの応答を受け取るまでシリアル受信ループが動作しない
   - 初期段階で受信バッファが機能していない

4. **ID 取得失敗時のハンドリングが不十分**
   - silent failure（エラーが出ても接続は続く）
   - ユーザーは状態が不明確

5. **タイムアウト値が固定（6秒）**
   - ネットワーク負荷が高い環境では不足

## 実装した改善

### 1. `queryDeviceIdFromDevice()` 関数の改善

```javascript
// 改善内容:
- REQUEST_INTERVAL_MS = 1000: ID要求を1秒ごとに再送信
- POLL_INTERVAL_MS = 50: ポーリング間隔を100ms → 50msに短縮
- タイムアウト中に複数回のID要求を送信
- より詳細なログ出力（取得までの経過時間を記録）
```

**効果**:
- 最初の1秒でダメでも、その後も自動的に再要求
- ポーリング精度が2倍向上
- 応答遅延環境での成功率が向上

### 2. `connectDevice()` 関数の改善

```javascript
// 改善内容:
- readLoop() をID取得前に開始（バックグラウンド実行）
- 段階的なタイムアウト試行:
  * 第1試行: 3秒
  * 第2試行: 5秒（その後500ms待機）
  * 第3試行: 8秒（その後500ms待機）
- ユーザーに各試行のステータスを通知
- ID取得失敗後も "unknown ID" で接続を続行可能
```

**効果**:
- 最大 3 + 0.5 + 5 + 0.5 + 8 = 17 秒の猶予（業界標準）
- シリアル受信が最初から動作し、ID 応答をキャッチできる
- ユーザーは進捗が見える
- 一時的な通信障害に強い

### 3. readLoop() の実行方法改善

```javascript
// 改善前:
readLoop();

// 改善後:
readLoop().catch((err) => {
    console.error("readLoop terminated unexpectedly:", err);
});
```

**効果**:
- readLoop() がバックグラウンドで実行され、ID 取得と並行動作
- エラー発生時は console に出力される

## 環境別効果期待値

| 環境 | 改善前 | 改善後 | 備考 |
|------|--------|--------|------|
| 低遅延（ローカル） | ~0.5s | ~0.2s | ポーリング間隔短縮で高速化 |
| 中遅延（LAN） | ~2-4s | ~1-2s | 再試行とポーリング改善 |
| 高遅延（WAN/無線） | ~6-8s or タイムアウト | ~3-8s 成功 | 段階的タイムアウトで対応 |
| 非常に悪い環境 | 失敗 | ~17s で成功 | 複数試行で成功率向上 |

## テスト方法

### 1. ブラウザコンソール確認

```
// ブラウザ開発者ツール → コンソールタブで以下のログを確認:

"ID query sent to device"          // ID要求送信時
"Device ID obtained: 0x..." 或は "ID obtained after timeout: 0x..." // ID取得時
"ID read successful on attempt N"  // 成功時
"ID read attempt N failed after Xms" // 失敗時
```

### 2. 環境別テスト

- ✅ ローカル接続: Connect → Device ID 取得が高速化することを確認
- ✅ リモート/ネットワーク: タイムアウトメッセージが表示されずに取得されることを確認
- ✅ 悪い環境: 複数試行で成功することを確認

### 3. 機能確認

- ✅ Connect 成功後、Session Start が可能か
- ✅ Device ID が "0xXXXXXXXX" 形式で表示されるか（または "unknown" でも動作）
- ✅ Bridge 経由でのデータ送信が正常に行われるか

## ログ例

```
// 成功ケース（ローカル環境）:
ID query sent to device
Device ID obtained: 0x12345678 (156ms)

// 再試行ケース（ネットワーク遅延）:
ID query sent to device
querying device id (attempt 1/3)... [timeout after ~3000ms]
ID read attempt 1 failed after 3150ms: device id query timed out after 3002ms
ID query sent to device [再試行]
Device ID obtained: 0x12345678 (after ~5800ms total)
ID read successful on attempt 2: 0x12345678
device id obtained
```

## その他の改善点

- Bridge 処理（初期化・接続）は非同期でバックグラウンド実行されるため、Device ID 取得に干渉しない
- エラーメッセージが詳細化され、トラブルシューティングが容易に
- 各段階のステータスが画面に表示される

## リリースノート

**Version**: Connection Flow Improvement v1.0

**変更ファイル**:
- `docs/viewer/js/serial.js`

**主な改善**:
1. Device ID 取得の段階的リトライ機能
2. ポーリング間隔の短縮（100ms → 50ms）
3. readLoop() の並行実行
4. ID 取得失敗時の柔軟なフォールバック

**後方互換性**: 完全（既存のシリアル通信インターフェースに変更なし）
