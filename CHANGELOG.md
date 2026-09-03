# パッチノート

## 2026-09-03 — 3バンドEQ / Camelotキー表記 / AI Match(ローカル推薦)

Ableton(打ち込み)× rekordbox(ライブラリ/ハーモニックミキシング)のいいとこ取りをさらに進める3つの機能を追加。

### 追加

- **3-Band ISO EQ(各デッキ)**
  Pioneer系ミキサーのチャンネルEQと同様、Low/Mid/High独立キルEQをデッキごとに追加(`backend/engine/effects.py: apply_three_band_eq`)。クロスオーバーは300Hz/3kHzで固定、各バンドのゲイン(0=キル・1=フラット・2=+6dB)はGain/Filter/Sendと同じくレーンに打ち込んでオートメーション可能。信号チェーンは EQ → Filter → Gain → Send/Crossfader の順。
  - `Deck.eq_low / eq_mid / eq_high`、`DeckAutomation.eq_low / eq_mid / eq_high` をプロジェクトスキーマに追加(既存プロジェクトJSONはデフォルト値1.0で自動補完されるため後方互換)。
  - UI: 各デッキのつまみ列に「3-BAND EQ」セクションを追加。既存のGain/Filter/Sendと同じ挙動(数値入力・レーン展開・右クリックでポイント一括削除)。

- **Camelotキー表記 + ハーモニックミキシング対応**
  BPM/キー解析結果にCamelot表記(例: `8A`, `8B`)を追加(`backend/harmonic.py: camelot_of`)。ライブラリ一覧にBPMチップと並べてCamelotバッジを表示。相性の良いキー(同一・±1・相対長短調)がひと目で分かる。

- **AI Match(ローカル・オフライン推薦エンジン)**
  ライブラリパネルに「🎯 AI Match」トグルを追加。選択中のクリップ(または armed 中のライブラリ曲)を基準に、BPM近似度(半分・倍テンポも考慮)とCamelotキー相性を加重スコアリングし、ライブラリを近い順に並べ替えて `🎯 xx%` バッジで表示。
  - クラウドAPIは一切使わないルールベースのローカル推薦(`GET /api/library/suggestions?bpm=&camelot=&exclude=&limit=`)。「gemini nano程度のローカルAIでも可」という要件に対し、まずは即時応答・完全オフラインな決定的スコアリングを実装(将来的にオンデバイスモデルへの置き換えも可能な形でAPIを分離)。

### 変更点の技術メモ

- EQのバンド分割はブロック単位ではなく全バッファ一括のIIRフィルタ2本(ローパス/ハイパス)+差分でミッドを算出する方式。クロスオーバー周波数は固定でゲインのみ時間変化するため、既存のDJ Filter(スイープ用にブロック処理が必要)より軽量。
- `library.suggest_matches` はキャッシュ済みライブラリ全体を対象にスコアリングするだけなので追加のディスクI/Oや解析は発生しない。

### 既知の制約

- Camelot表記はキー推定(`librosa.feature.chroma_cqt` ベースの相関マッチ)の精度に依存するため、他のBPM同様に目安。
- AI Matchはキー/BPMのみに基づく評価で、曲調やエネルギーレベルは考慮しない。
