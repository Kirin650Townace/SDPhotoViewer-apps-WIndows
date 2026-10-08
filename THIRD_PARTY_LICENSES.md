# 同梱ライブラリのライセンス（第三者ソフトウェア）

このアプリは次のライブラリを使って動いています。
**インターネット等で配布（公開）する場合は、下の内容に沿った対応が必要です。**

- 調査日: 2026-10-08
- 対象バージョン: 開発環境（Windows / Python 3.10）で実際に使っているもの
- 各ライセンスの正文は `licenses/` にあります（配布用フォルダにも自動でコピーされます）

---

## 1. 一覧

| ライブラリ | 版 | ライセンス | 配布するときの扱い |
| --- | --- | --- | --- |
| **PySide6（Qt for Python / Qt 本体）** | 6.12.0 | **LGPL-3.0-only**（または GPL-2.0 / GPL-3.0、商用） | LGPLv3 の条件を守れば同梱可。**ライセンス文の同梱**と、Qt のライブラリを**差し替えられる形**（別ファイルの DLL として同梱）にすることが必要 |
| **PySide6-Fluent-Widgets（qfluentwidgets）** | 1.11.3 | **GPLv3** | **アプリ全体を GPLv3 で配布し、ソースコードを入手できるようにする必要があります**（下の「3」参照） |
| Pillow | 12.3.0 | MIT-CMU（HPND） | ライセンス文を同梱すれば可 |
| pillow-heif（HEIC 対応） | 1.8.0 | 本体は BSD-3-Clause だが、**配布用のビルド済みファイル（wheel）は GPLv2**（同梱の libheif / libde265 = LGPLv3、x265 = GPLv2 のため） | ライセンス文（`LICENSES_bundled.txt`）を同梱する。**GPL の条件は PySide6-Fluent-Widgets 側とまとめて1つ**（アプリ全体を GPLv3 で公開）で足ります |
| numpy | 2.3.5 | BSD-3-Clause | ライセンス文を同梱すれば可 |
| imageio-ffmpeg（ffmpeg 本体を同梱） | 0.6.0 | BSD-2-Clause（**同梱の ffmpeg は GPLv3 ビルド**） | ライセンス文を同梱し、ffmpeg のソース入手先を案内する（下の「4」参照） |
| rawpy（使う場合のみ） | 0.19 以降 | MIT（LibRaw は LGPL-2.1 / CDDL-1.0） | ライセンス文を同梱すれば可。LibRaw 部分は LGPL の条件（差し替え可能な形）に注意 |
| PyInstaller（exe を作る道具） | 6.x | GPL-2.0-or-later + **ブートローダ例外** | 例外があるため、**作った exe を GPL にする必要はありません**（道具として使うだけ） |

> 参考: PySide6 のメタデータは `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`、
> PySide6-Fluent-Widgets は `GPLv3`（同梱の LICENSE は GNU GPL v3 の正文）でした。

---

## 2. 結論（先に知りたいこと）

- **ライブラリのライセンス的には配布できます**。ただし **GPL のライブラリを3つ含んでいる**ため
  （PySide6-Fluent-Widgets = GPLv3、pillow-heif のビルド済みファイル = GPLv2、同梱の ffmpeg = GPLv3）、
  このアプリを配布するなら **アプリ全体を GPLv3 として公開し、ソースコードを配れる状態にする**のが条件です。
- 「作ったものを無償で公開する」だけなら、**そのまま GPLv3 で公開するのが一番かんたん**です
  （ソースを GitHub などに置き、exe と一緒に案内する）。
- **ソースを公開したくない／アプリを販売したい**場合は、次のいずれかが必要です。
  1. **PySide6-Fluent-Widgets の Pro（有償）ライセンス**を購入する（GPLv3 の条件が外れます）
  2. Fluent 風の見た目を自前実装（または許諾の緩い別ライブラリ）に置き換える（作業量は大きめ）
- SNS などに**スクリーンショットを載せるだけ**なら、配布ではないので何も問題ありません。

---

## 3. GPLv3（PySide6-Fluent-Widgets）で配布する場合のやり方

1. ソースコードを公開する（例: GitHub のリポジトリ。このプロジェクト一式をそのまま置けます）
2. アプリのルートに **LICENSE**（GPLv3 の正文 = `licenses/GPL-3.0.txt`）を置く
3. README に「GPLv3 で公開していること」「対応するソースの場所」を書く
4. exe などの配布物には次のファイルを添える（`build_windows.bat` が自動で入れるようにしました）
   - `licenses/`（GPLv3 / LGPLv3 / 各ライブラリのライセンス文）
   - この `THIRD_PARTY_LICENSES.md`
5. 受け取った人が **ソースを入手してビルドし直せる**状態にする（ビルド手順を README に書いておく）
6. 「追加の制限を課さない」（GPLv3 より厳しい条件を付けない）

---

## 4. ffmpeg（動画のサムネイル用）について

- `imageio-ffmpeg` は **ffmpeg の実行ファイルを同梱**しています。このビルドは
  `--enable-gpl --enable-version3` 付きの **GPLv3** ビルドです（`ffmpeg -version` で確認できます）。
- ffmpeg は**別プログラムとして呼び出している**だけなので、アプリ全体を GPL にする必要はありませんが、
  配布するときは次の対応をしてください。
  - ffmpeg の **ライセンス文（GPLv3）を同梱**する
  - **ffmpeg のソースコードの入手先**を案内する（例: <https://ffmpeg.org/download.html>、
    同梱ビルドの入手元 <https://johnvansickle.com/ffmpeg/>）
- 同梱している ffmpeg は `_internal/imageio_ffmpeg/binaries/` に入っています。

- ffmpeg を同梱したくない場合は、`requirements.txt` から `imageio-ffmpeg` を外し、
  「動画のサムネイルは ffmpeg が入っているときだけ使える」形にもできます（その場合は機能の一部が無効）。

---

## 5. Qt（PySide6）を LGPLv3 で同梱するときのポイント

- **ライセンス文（LGPLv3）を同梱**する：`licenses/LGPL-3.0.txt`
- **利用者が Qt を自前のビルドに差し替えられる形で配る**：
  本アプリの exe は `_internal` に Qt の DLL を**別ファイルとして**置く形（PyInstaller の onedir）なので、
  この条件を満たしています（1ファイルにまとめる `--onefile` は避けるか、その分の注意が必要）。
- Qt の著作権表示（The Qt Company）と LGPLv3 であることを README などに書く。
- Qt のソース入手先を案内する：<https://download.qt.io/source/>

---

## 6. 配布物に入れるファイル（自動でコピーされます）

`build_windows.bat`（`python tools/build_exe.py`）で作ると、`dist/` のアプリフォルダに
次のファイルが自動で入ります。フォルダごと渡してください。

```
dist/SDフォトビューア/
├── SDフォトビューア.exe
├── _internal/                     ← ライブラリ（消さないでください）
├── README.md / 使い方.md
├── THIRD_PARTY_LICENSES.md        ← この文章
├── licenses/                      ← ライセンス文（GPLv3 / LGPLv3 / 各ライブラリ）
│   ├── README.txt                 ← どれが何のライセンスかの一覧
│   ├── GPL-3.0.txt
│   ├── LGPL-3.0.txt
│   └── （インストールされているライブラリのライセンス文）
└── ログを保存.txt
```

---

## 7. GPL を避けたいとき（ソースを公開したくない場合）

「GPL のライブラリを使わない」形にすれば、アプリを自前のライセンス（非公開）で配布できます。
その場合に置き換えるものは次の3つです。

| 今使っているもの | 置き換え先 |
| --- | --- |
| PySide6-Fluent-Widgets（GPLv3） | ①Pro（有償）ライセンスを買う／②普通の Qt 部品（PySide6 標準）＋自前の QSS で見た目を作る |
| pillow-heif のビルド済みファイル（GPLv2） | HEIC 対応をやめる（JPEG/PNG/RAW のみ）／x265 抜きで自分でビルドする |
| 同梱の ffmpeg（GPLv3） | 動画サムネイルをやめる／LGPL ビルドの ffmpeg を自分で用意し、ユーザーが各自入れる形にする |

このうち一番大きいのは **PySide6-Fluent-Widgets** です。Pro ライセンスを買うのが一番早く、
見た目をそのまま保ったまま GPL の条件を外せます。

## 8. 自分の写真・サンプル・スクリーンショット

- `sample_sd/` の写真は**このプロジェクト用に生成したダミー画像**なので、配布物に含めて問題ありません。
- SD カードから読み込んだ写真はアプリが表示するだけで、**コピー・保存・送信は一切しません**
  （読み取り専用。設定は自分の PC の `QSettings` に保存されるだけです）。
- 公開するときは、**実際の写真（人物・位置情報）入りのスクリーンショットを載せない**ようご注意ください。
