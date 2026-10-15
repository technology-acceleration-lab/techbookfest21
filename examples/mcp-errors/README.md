# MCP Toolエラー設計の最小検証

記事は [`src/02-mcp-tool-errors.md`](../../src/02-mcp-tool-errors.md)、版・観測結果・未検証事項の正本は [`docs/mcp-errors/verification.md`](../../docs/mcp-errors/verification.md) です。

## 実行

Python 3.14系とuvが必要です。実測はPython 3.14.6、uv 0.11.26で行いました。

```sh
cd examples/mcp-errors
uv sync --frozen
uv run --frozen pytest
uv run --frozen python probe.py > /tmp/mcp-errors.json
```

`uv.lock` が推移的依存を固定します。初回の同期にはPyPIへの接続が必要です。テストとprobe自体には外部ネットワーク、APIキー、LLM利用料は不要です。ルートからは `pnpm run test:mcp-errors` でも実行できます。

## ファイル

| ファイル | 役割 |
| --- | --- |
| `server.py` | 読み取り専用Tool、定型エラーへの変換、上限付きHTTP再試行 |
| `lab_server.py` | SDKの実際の応答を調べるための小さな反例群 |
| `probe.py` | stdioの実通信と模擬HTTPの応答をJSONとして標準出力へ採取 |
| `test_errors.py` | 応答形式、実行回数、情報露出を検証 |

`lab_server.py` には情報露出を実証する意図的に危険なToolがあります。ダミー値だけを使い、ローカル検証専用としています。公開サーバーとして配備しないでください。

`server.py` の単体起動先 `https://example.invalid` は実APIではありません。動作例はテストの `httpx.MockTransport` から取得します。実サービスへの接続設定や認証処理はこのサンプルに含めていません。

`probe.py` の出力には試験用の `DUMMY_SECRET_DO_NOT_USE` が現れます。これは「漏れなかった」という結果だけでなく、意図的なエラー文や検証エラーでは値が残ることも記録するためです。実在の秘密情報を試験入力に使わないでください。
