# MCP Toolエラー設計: 検証記録

検証日: 2026-10-15 JST。原稿: [`02-mcp-tool-errors.md`](../../src/02-mcp-tool-errors.md)。再現手順: [`サンプルREADME`](../../examples/mcp-errors/README.md)。生の観測値: [`results.json`](results.json)。SDK更新時はロックを更新して再実行し、本記録と原稿の該当箇所を照合する。

## 調査範囲と採用した構成

- 作業開始時の合同誌リポジトリは `technology-acceleration-lab/techbookfest21`、`main` の `f8d6979`。未コミット変更はなかった。`codex/mcp-tool-error-design` で作業した。
- このリポジトリにProject AGENTSやPython実装はなく、Vivliostyleの設定、B5テーマ、Node依存のロック、PDFビルドCIがあった。既存原稿は扉・前書き・後書き・著者・奥付の雛形で、執筆済みの本文はなかった。
- Codexの登録プロジェクトと接続済みGitHubリポジトリ一覧を確認した。ローカルの登録済みプロジェクトを含むWorkspace内のPython実装・マニフェストを `FastMCP`、`MCPServer`、`from mcp` 等で検索したが、再利用可能なMCPサーバーは見つからなかった。すべての過去ブランチ、未接続のアカウント、未取得のリポジトリを調べたという意味ではない。
- 他プロジェクトは読み取り調査のみ。非公開プロジェクトのコードやデータを本リポジトリへ転載していない。検証は `examples/mcp-errors` に独立して追加し、既存Node依存とPython依存を分離した。

## 固定した版と一次資料

| 対象 | 確認内容 |
| --- | --- |
| MCP公式仕様 | `latest` が **2026-07-28** へ転送されたため、その版付きURLを採用 |
| Python SDK | PyPIとGitHub Releasesで **2.3.0** を最新安定版として確認。PyPI公開日時は2026-10-02 UTC |
| Python / 実行基盤 | CPython **3.14.6**、macOS arm64、uv **0.11.26** |
| 主要依存 | `mcp-types 2.3.0`、`pydantic 2.14.1`、`anyio 4.15.1`、`httpx 0.28.1`、`pytest 8.4.2` |
| 再現用依存 | `examples/mcp-errors/uv.lock`。取得した配布物とSDKソースのハッシュは [`sources.json`](sources.json) |

`mcp 2.3.0` の高水準APIは `mcp.server.MCPServer` と `mcp.Client`。会話の背景で言及されたv1の `FastMCP` を前提に実装していない。インストール先のSDKソースとv2.3.0タグの関係もハッシュで確認した。Web上のSDKガイドは更新され得るため、実測とタグ付き実装を根拠の中心にした。

一次資料:

1. [MCP 2026-07-28 Tools / Error Handling](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#error-handling): プロトコルエラー、Tool実行エラー、クライアントがLLMに提示する際のMAY / SHOULD。
2. [CallToolResultスキーマ](https://modelcontextprotocol.io/specification/2026-07-28/schema#calltoolresult): `resultType`、`isError` の既定の解釈、`structuredContent`。
3. [基本仕様の `_meta`](https://modelcontextprotocol.io/specification/2026-07-28/basic/index#meta): 新版の各要求が持つプロトコル版・クライアント情報・能力。stdio試験でも付与。
4. [SDK v2.3.0リリース](https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.3.0)、[PyPI](https://pypi.org/project/mcp/2.3.0/): 実験対象の版。
5. [ToolManager v2.3.0](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/tools/tool_manager.py): 未知のToolに `ToolError`。
6. [Tool.run v2.3.0](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/tools/base.py): 引数検証、明示エラー、想定外例外の区別。
7. [MCPServer v2.3.0](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/server.py): `_handle_call_tool` が `MCPError` を再送出し、他のTool失敗を `CallToolResult` へ変換。
8. [SDK The Client](https://py.sdk.modelcontextprotocol.io/client/#is_error-whether-the-tool-failed)、[Handling errors](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/)、[Testing](https://py.sdk.modelcontextprotocol.io/get-started/testing/): 公開APIの説明。
9. [RFC 9110 §10.2.3](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after): `Retry-After` の秒数・HTTP日時。[RFC 9110 §9.2.2](https://www.rfc-editor.org/rfc/rfc9110.html#name-idempotent-methods): 冪等な要求と自動再試行の条件。

## 実験方法

### SDK / stdioの実通信

`probe.py` が別プロセスで公式SDKのstdioサーバーを起動し、最初に `server/discover`、続いて18種類のJSON-RPC要求を送信する。Pythonクライアントの型構築で拒否される不正な要求も送れるよう、標準入出力へJSON行を直接書き込む。要求と応答は省略せず `results.json` の `wire` に保存した。

加えて `Client(server)` による実際のSDKのインメモリ接続で、関数実行回数、クライアント例外、サーバーログを検証した。SDKの非公開メソッドへ直接呼び出して作った結果ではない。`raise_exceptions=True` を指定した場合でも、想定したTool実行エラーが戻り値になることをテストした。

### 外部APIの模擬応答

`httpx.MockTransport` によりAPIのHTTP応答・タイムアウトを模擬し、公式SDKのインメモリ接続から `get_record` を呼んだ。10ケースの結果・HTTP要求数・待機の指定を `results.json` の `upstream` に保存した。待機関数は秒数を記録する関数へ差し替えた。実ネットワークや実時間の待機は使っていない。

## 観測結果

### SDKが返す形式

| ケース | 実測 | 証拠キー / テスト |
| --- | --- | --- |
| 未知のメソッド | `error.code=-32601` | `wire.unknown_method` |
| `tools/call` のname欠落 / argumentsが配列 | `error.code=-32602` | `wire.missing_tool_name` / `arguments_not_object` |
| 未知のTool | `result.isError=true`、`Unknown tool: ...` | `wire.unknown_tool` |
| Tool引数の欠落・不正型・範囲外・整数の文字列 | `isError=true`、Tool関数は0回 | `wire.missing_argument` 等 / `test_invalid_arguments_never_enter_tool` |
| 文字列 / エラー風の辞書をreturn | `isError=false` | `wire.returned_string` / `returned_dict` |
| ToolError / 明示的CallToolResult | `isError=true` | `wire.tool_error` / `explicit_is_error` |
| MCPError | `error.code=-32602`、Python ClientでもMCPError | `wire.mcp_error` / `in_memory.protocol_exception` |
| ToolErrorに対するSDKの再実行 | 1回のcall_toolに対し関数実行は1回 | `in_memory.tool_body_calls` |

**仕様とSDKの差:** 公式Tools文書は未知のTool名をプロトコルエラーの例としている。しかし今回の `MCPServer` はTool実行エラーを返した。SDKのClient文書もこの挙動を明記している。仕様の分類と高水準SDKの観測値を分け、SDK全般・他のサーバー実装に一般化しない。

### 外部API変換と再試行

| 模擬API | 要求数 | 待機の指定 | 結果 |
| --- | ---: | --- | --- |
| 200 | 1 | なし | IDとnameのみ公開 |
| 404 | 1 | なし | NOT_FOUND / change_record_id |
| 401 / 403 | 各1 | なし | ACCESS_DENIED / ask_operator |
| 429→200、Retry-After: 1 | 2 | 1秒 | 成功 |
| 500→500→200 | 3 | 0.25、0.5秒 | 成功 |
| 503継続 / ReadTimeout継続 | 各3 | 0.25、0.5秒 | RETRY_EXHAUSTED / stop |
| 429、Retry-After: 20 | 1 | なし | RETRY_LATER / defer_to_host、待機の助言20秒 |
| 200で不正JSON | 1 | なし | INVALID_UPSTREAM_RESPONSE |

初回を含め3回、要求ごとのタイムアウト2秒、Tool内の一回の待機上限2秒はアプリケーション独自の方針。`Retry-After` を短縮して再試行しない。HTTP日時形式・過去日時・不正値・極端に長い値はパーサー単体でも検証した。1日を超える待機指定は数値の助言を返さずホストへ判断を渡す。全体期限やホスト側スケジューラーの実装は含まない。

### 内部情報の露出

ダミー値 `DUMMY_SECRET_DO_NOT_USE` だけを用い、応答のJSON全体を照合した。

| 経路 | クライアントへの露出 | その他 |
| --- | --- | --- |
| RuntimeError内のメッセージ | なし | サーバーのERRORログにはトレースバックとダミー値あり |
| 明示的ToolErrorの文言 | あり | SDKが開発者の指定文を公開 |
| 明示的MCPError.data | あり | プロトコルエラーでも任意データは公開 |
| 不正な整数入力 | あり | 検証文言のinput_valueに入力文字列が残る |
| サンプルAPIのdebug / internal_note / 不正本文 | なし | 公開項目の選択と定型文への変換による |

`ToolError(str(exc))` への一律変換が危険であるという設計判断を、上記の「明示的なエラー文は公開される」という観測で支える。入力検証エラーの一般的なサニタイズは未実装であり、サンプルがあらゆる機密情報を隠すとは主張しない。

## 検証コマンドと結果

依存同期・試験の実行方法はサンプルREADMEに集約。固定ロックで同期後、`pytest`: **25 passed**。stdio 18ケース、模擬HTTP 10ケースを採取した。`results.json` の `environment` に実行版を保存した。

PDFの検証結果は本記録末尾の「組版確認」に記載する。原稿は共通テーマを使い、章だけに効くモノクロCSSを追加した。既存の扉・前後書き・著者・奥付・共有テーマ本文は変更しない。

## 未検証事項と今後の実験

- **LLMの復旧:** モデル呼び出しは行っていない。説明文による復旧率の差、モデル間の差、繰り返し試行時の分布は不明。実験するならモデル版、温度、プロンプト、ホスト、最大Tool呼び出し回数、成功条件、ケース数、繰り返し数を先に固定する。
- **実APIと認証:** 実在の外部API、レート制限解除、実認証、MCP自身のHTTP認証の失敗は未実施。
- **HTTPトランスポートと製品:** Streamable HTTP、SSE、CodexやClaude等の実ホストの表示・モデルへの提示内容は未実施。stdioの結果だけで判断しない。
- **版と実装の違い:** SDK v1や他言語SDK、低水準Server、第三者製FastMCPは未実施。v2.3.0に固定した結果。
- **制御:** 実時間の待機、全体タイムアウト、ジッター、キャンセル、複数クライアント、二重の再試行、更新処理の冪等性・二重実行は未実施。
- **情報保護:** 入力検証エラーをSDKより前でサニタイズする仕組み、ログのマスキング、成功データのプロンプトインジェクション対策は未実施。ダミー文字列の照合は包括的なセキュリティ監査ではない。
- **出力スキーマ:** サンプルToolにはoutputSchemaを公開していない。成功・失敗の共通スキーマと各ホストのエラー時検証は未実施。

## 組版確認

- `pnpm run build:mcp-errors`: 成功。**JIS-B5（182×257mm）、7ページ**。単独PDFは `mcp-errors.pdf`。
- `pnpm run build:print` / `pnpm run build`: ともに成功。現時点の合同誌全体は13ページで、章は4〜10ページに入る。
- ブラウザーはローカルのGoogle Chromeを `--executable-browser` で明示。PDFの生成情報はVivliostyle.js 2.45.0 / Chrome 155。依存は既存 `pnpm-lock.yaml` に固定したCLI 11.2.0 / VFM 2.7.2。
- この実行環境ではNode 24.19.0 / pnpm 11.25.0を使用。リポジトリの `mise.toml` が指定するNode 24.2.0 / pnpm 12.3.4そのものでは実行していない。依存のロックや既存ツール指定は変更していない。
- 全7ページをPNGにレンダリングして目視。表・コードの欠け、コードブロックのページ分割、参考文献だけの余分な最終ページがないことを確認した。PDF本文のRGB描画色もすべてR=G=Bで、色による意味の区別を使っていない。
- ビルド中に既存 `fonts/IBMPlexSans.css` / `IBMPlexSerif.css` が参照する未収録のサブセットフォントへの404が176件出る。該当CSSは開始時から未変更。単独章・合同誌の両方でビルド完了し、今回の文字列は表示できているが、フォント参照の整理は合同誌の共通基盤として別途必要。
- 合同誌全体のPDFをPopplerで解析すると長いname tokenの警告も出る。章単独の解析では発生しなかった。共通雛形を含む全体PDFについてPDF/X等の印刷所向けプリフライトは行っていない。
- 日本語リンターは93/100。語尾の連続と「実在の認証情報ではなくダミー値」という対比の2候補を目視し、動作説明と試験条件を保つため変更しなかった。

著者の個人名、合同誌全体のタイトル、奥付等の既存TODOはこの章の追加では確定していない。単独PDFのauthorメタデータは発行元の「技術加速研究所」とした。入稿前には編集者が全体メタデータ・共通フォント・最終ページ数を確認する。
