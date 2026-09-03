# DJ Mix Studio

打ち込みでDJミックスを組み立てて、1本のWAVに書き出すためのローカルアプリ。
Ableton(タイムラインに打ち込む)× rekordbox(ライブラリ/BPM解析)のいいとこ取りを狙った構成です。
UIはMaterial 3 Expressive(色・形状・タイポグラフィ・スプリングモーションのトークンを自前で実装、Roboto可変フォント同梱でオフライン動作)。

## 起動

### exe版(配布・普段使い向け)

```powershell
dist\DJMixStudio\DJMixStudio.exe
```

ブラウザではなく専用のウィンドウで開きます。プロジェクト・書き出したWAV・ライブラリキャッシュは `%APPDATA%\DJMixStudio\` に保存されるので、exeフォルダごとどこに置いても、Windowsを再起動しても内容は引き継がれます。exeがまだ無い/作り直したい場合は下記でビルドしてください(初回は数分かかります)。

```powershell
pip install -r requirements.txt
pip install pyinstaller pyinstaller-hooks-contrib pywebview
powershell -ExecutionPolicy Bypass -File build_exe.ps1
```

出力: `dist\DJMixStudio\DJMixStudio.exe`(フォルダごと配布。単体ファイルではなくフォルダ一式で約400MB)。

### 開発版(ブラウザ・コード変更を試すとき向け)

```bash
pip install -r requirements.txt
python scripts/generate_demo_library.py   # 初回のみ: デモ用の合成音源を作成
python run.py
```

ブラウザが自動で `http://127.0.0.1:8790/` を開きます。データは `backend/data/` 配下(exe版とは別管理)。

## できること

- **ライブラリ**: フォルダを指定してScanすると、配下の音源(wav/mp3/flac/aiff/ogg/m4a)を再帰的に解析してBPM・キー・波形を表示。解析結果はキャッシュされ、ファイルが変わらない限り再解析しません。
- **ハーモニックミキシング(Camelot Wheel)**: rekordbox/Mixed In Key互換のCamelotコード(例: 8A)をキー解析から自動算出し、色分けしたチップで表示。数字が近い/同じレターの相対調ほど色相が近くなるので、隣接キーが視覚的にひと目でわかります。
- **試聴プレイヤー + ホットキュー**: ライブラリ項目の▶ボタンまたは波形クリックで、タイムラインに置かずにそのまま音源を試聴できます(rekordbox風のプレビュー)。再生中に数字キー1〜4でメモリーキューを最大4つ打ち込み・ジャンプ(Shift+数字でクリア)。キューはライブラリキャッシュに保存され、次回起動後も残ります。
- **AI Mix Assistant(✨ Suggest compatible tracks)**: アーム中/選択中の曲を基準に、Camelotの調和距離とBPM適合度(同一・倍/半分テンポなど)をローカルで採点し、ライブラリから合う曲を提案します。クラウドやモデルのダウンロードは一切使わない、オンデバイスのルールベース推薦(Gemini Nano的な"軽量ローカルAI"の代わりに、解析済みメタデータだけで完結する決定的なスコアリングを採用)。
- **デッキはAbleton的に何本でも**: 「+ Track Deck」「+ Shot Deck」で好きな数だけ追加。Track Deckは曲/ループ用(BPM同期のタイムストレッチあり)、Shot Deckは単発ネタ用(ジングル・煽りボイス・効果音など、デフォルトは原速再生)。Shot Deckには「Choke grp」があり、同じ番号同士は後発の発音が先発を止める(サンプラーのvoice steal)。
- **打ち込みオートメーション**: 各デッキのGain(フェーダー)・Filter(LPF⇄HPFの1ノブフィルター)・Reverb Send、それにMaster GainとCrossfader(A/Bをイコールパワーでミックス)は、つまみで固定値を決めるか、レーンをクリックしてブレークポイントを打ち込むと時間変化するオートメーションになります。ポイントは右のInspectorで時間・値を数値入力でき、ドラッグでも動かせます。
- **クリップ編集**: ライブラリの項目をクリックしてアーム→デッキのレーンをクリックで配置(アームしたままだと連続でスタンプ配置できます)。ドラッグで移動、右端をドラッグでソース長を調整。Inspectorでソースの開始位置・長さ・ループ回数・トリムゲイン・フェード・ピッチ(半音)・リバースを数値で追い込めます。スナップ(拍単位)はツールバーのトグルでON/OFF可能。
- **Undo / Redo**: クリップ移動・オートメーション打ち込み・デッキ追加削除など、意味のある操作ひとつごとに1ステップとして記録。Ctrl+Z / Ctrl+Shift+Z(またはツールバーの⟲⟳)でAbleton同様に何段階でも戻せます。
- **リバーブ**: 各デッキのSendから共通のリバーブバス(Room/Damping/Width/Pre-delay/Return)に送る、実機ミキサーと同じセンド構成。
- **Preview / Export**: PreviewはUI上部のプレイヤーで即再生確認。Export WAVでプロジェクト全体を1本のWAV(24bit/プロジェクトのサンプルレート)に書き出します。
- **保存/読込**: プロジェクトはJSONで保存され、一覧から読み込めます。

## 既知の制約

- BPM自動解析は目安です(特に単純なシンセ/パーカッション主体の音源だと数BPMずれることがあります)。Inspectorの「Source BPM」欄で手動修正できます。キー解析も同様に目安で、Camelotコードはその推定キーから機械的に導出しているため、解析が外れていればコードもずれます。
- タイムライン上での再生はリアルタイムのオーディオエンジンではなく、Preview/Exportのたびにオフラインレンダリングする方式です(Ableton的な「即座に音が鳴る」体験ではありません)。長いミックスほどレンダリングに数秒〜数十秒かかります。試聴プレイヤー(ライブラリの▶)は元ファイルをブラウザの`<audio>`でそのまま再生するので、こちらは即時再生です。
- AI Mix Assistantはローカルのルールベース採点(Camelot距離 + BPM適合度)で、学習済みモデルやクラウドAPIは使っていません。「聴いた上での」提案ではなく、あくまで解析済みメタデータからの機械的な絞り込みです。
- Undo/Redoはブラウザタブ内のセッション限りです(ページを閉じる・リロードすると履歴は消えます)。保存済みプロジェクトの内容自体は影響を受けません。
- ローカル単一ユーザー向けの前提で、認証や複数プロジェクトの同時編集は考慮していません。
- exeの初回起動時、バックグラウンドでデモライブラリを解析するため(numbaのJITウォームアップで最大30秒程度)ライブラリ欄が一瞬空に見えることがあります。自動で埋まります。

更新履歴は [CHANGELOG.md](CHANGELOG.md) を参照してください。

## 構成

- `backend/` — FastAPI。`analysis.py`(BPM/キー/Camelotコード解析), `library.py`(フォルダScan+キャッシュ+ホットキュー保存), `engine/`(タイムストレッチ・フィルター・リバーブ・ミックスダウン), `models.py`(プロジェクトのスキーマ), `main.py`(API。開発版/exe版でデータ保存先を自動切り替え。試聴用の音源配信・ホットキュー保存エンドポイントを含む)。
- `frontend/` — 素のHTML/CSS/JS + Roboto可変フォント同梱。`style.css`がMaterial 3 Expressiveのデザイントークン、`app.js`がタイムラインCanvas・オートメーション編集・Inspectorなど全UIロジック。
- `desktop_app.py` — exe版のエントリポイント。バックグラウンドスレッドでFastAPIサーバーを起動し、pywebviewのネイティブウィンドウで表示。
- `build_exe.ps1` — PyInstallerでのビルドスクリプト。`frontend/app.ico`をアイコンに使用。
- `scripts/generate_demo_library.py` — デモ用の合成音源(ビート/ベースライン/パッド/一発ネタ)を`backend/data/sample_library/`に生成。
- `scripts/generate_icon.py` — `frontend/app.ico`を生成。
- `scripts/smoke_test.py` — UIを介さずに解析→レンダリングまでを一気通貫でテストする動作確認スクリプト。
