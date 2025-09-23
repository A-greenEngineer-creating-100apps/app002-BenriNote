## 便利ノート
#app002-BenriNote

PySide6 で作った「軽量ノートアプリ」です。   「ちょっとしたメモ」「ToDo 管理」「常駐事項の情報確認」を 1 画面でできるようにしました。

## 主な機能

<img width="832" height="626" alt="image" src="https://github.com/user-attachments/assets/6f3bc010-9925-435c-bb62-daa257224862" />

- ✅ **ToDo リスト**
  - ダブルクリックで編集（文字色・下線など）
  - 完了チェック → アーカイブに移動
  - アーカイブはタブ切り替えで表示・編集・削除可能

- 📌 **常駐事項**
  - ドラッグ＆ドロップで並べ替え
  - ダブルクリック編集ポップアップ
  - 簡単なカテゴリ管理として利用できます

- 📝 **メモ (Memo A / Memo B)**
  - 左右分割
  - 白背景、下線や色付け編集可能

- 🖥 **ウィンドウ操作**
  - 「常に手前に表示」トグル（ツールバー & トレイ）
  - ツールバーをダブルクリックで **70% サイズ ↔ 前回サイズ** にトグル
  - OnTop ↔ Normal を切り替えても × ボタンが押せなくなる問題を解消済み
  - 起動時は必ず **Normal (OnTop OFF)** でスタート

- 🛎 **システムトレイ常駐**
  - 「常に手前に表示」トグル

- 💾 **データ保存**
  - ToDo / アーカイブ / 常駐事項 / メモ内容を JSON 形式で保存
  - 保存先は OS のユーザーローカル領域（例: Windows の `%LOCALAPPDATA%\BenriNote`）

## インストールと実行

### 必要環境
- Python 3.9+
- [PySide6](https://pypi.org/project/PySide6/)
- PySide6>=6.6

### セットアップ

```bash
git clone https://github.com/<yourname>/benrinote.git
cd benrinote
pip install -r requirements.txt
python benrinote.py

## 備忘メモ

- Python 環境がなくても使えるようにする（PyInstaller などで EXE 化を検討？）
- アイコンやテーマの追加、UIもっとおしゃれにすること。
