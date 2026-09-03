# Patch Notes

## 2026-09-03 — rekordbox連携機能: Hot Cue / Camelotキー / Mix Assistant / Beat Loop

Ableton(打ち込み・ループ)× rekordbox(ライブラリ解析・選曲支援)のうち、rekordbox側で不足していた「選曲・キューイング」まわりを追加。

### 追加

- **Camelotキー表記**: ライブラリ解析が調(例: `C major`)に加えてCamelotホイール表記(`8B`など)を算出。ライブラリ項目にホイールの色相で塗られたチップとして表示され、rekordbox同様にひと目でハーモニックミキシングの相性が分かるように。
- **Energy(エネルギー感)**: RMSベースの粗い0–1指標を解析時に算出し、ライブラリ項目に小さなエナジーメーターとして表示。静かなイントロ向きの曲とピークタイム向きの曲を見分けやすくした。
- **Hot Cue(メモリーキュー)**: ライブラリの波形をクリックしてキューポイントを打てるように(rekordboxのホットキュー相当)。トラック本体に紐づく永続データとして`backend/data/library_user.json`に保存され、解析キャッシュの再生成や再解析後も残る。既存マーカー付近をクリックすると削除。クリップInspectorでは、選択中クリップの元トラックにキューがあればチップとして並び、クリックひとつで「Src offset」をそのキュー位置に設定できる — rekordboxのキューからAbletonのクリップ配置に一本の動線で橋渡し。
- **Mix Assistant(ローカル・ルールベースの選曲支援)**: ライブラリでトラックを1曲アーム(選択)した状態で「🎯 Mix Assistant」を押すと、BPM比(オクターブ違いも考慮)とCamelotキーの近さ(同一/隣接/相対長短調を優先)を重み付けした相性スコアで残りのライブラリを並べ替え、パーセンテージ表示する。**クラウドAIやモデルのダウンロードは一切使わない、完全オフラインの単純なヒューリスティック**(「gemini nano程度のローカルAI」という要望に対し、実態を偽らないよう明示的にルールベースと位置付けている)。
- **Beat Loop(CDJ/Ableton風のクイックループ)**: クリップInspectorに1/2/4/8/16/32拍のワンクリックボタンと÷2・×2ボタンを追加。ソースBPM(不明ならプロジェクトBPM)を基準に`source_length`を正確な拍数へスナップする。従来はSrc lengthを秒数で手打ちする必要があった。

### 変更

- `backend/library.py`: 解析キャッシュにバージョンタグ(`_v`)を導入。camelot/energyフィールドを持たない旧形式のキャッシュエントリは次回スキャン時に自動で再解析される(BPM/キー自体の再解析結果は変わらない)。
- ライブラリキャッシュのユーザーメタ(`library_user.json`)はフォルダの再スキャンでファイルが消えた場合のみ追従して削除される。

### API

- `POST /api/library/cues` `{path, cues:[{time, label, color}]}` を追加。トラックのキューリストを丸ごと置き換えて、マージ済みのライブラリエントリを返す。未スキャンのパスは404。
- `GET /api/library` / `POST /api/library/scan` / `POST /api/library/reanalyze` のレスポンスに `camelot`・`energy`・`cue_points` フィールドを追加(既存フィールドの削除・改名なし)。

### 検証

- `scripts/smoke_test.py`(解析→オフラインレンダリング一気通貫)が引き続き成功することを確認。
- `backend/library.py`のスキャン/キュー保存/旧キャッシュの自動再解析/未知パスへのキュー保存エラーをスクリプトで直接検証。
- FastAPI `TestClient` で `/api/library/scan` → `/api/library/cues` → `/api/library` のラウンドトリップと、未知パスでの404を確認。
- Playwrightでブラウザを起動し、実際のUIで Scan → アーム → Hot Cue追加 → Mix Assistant のスコア表示 → クリップ配置 → Beat Loopボタンでの`source_length`変更 → クリップInspectorのキューチップでの`source_offset`ジャンプまでを一気通貫で操作確認(コンソールエラーなし、`favicon.ico`の404のみで既存動作と同じ)。

### 既知の制約(変わらず)

- タイムライン上での再生はオフラインレンダリング方式のまま(リアルタイムオーディオエンジンではない)。今回追加したMix AssistantとHot Cueは選曲・準備を支援するもので、CDJ的な「その場でスクラッチ/頭出し」の代替にはならない。
- Mix Assistantのスコアリングはあくまでルールベースの目安。ジャンルやアレンジの相性までは判断しない。
