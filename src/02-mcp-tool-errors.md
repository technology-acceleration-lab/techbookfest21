---
class: chapter mcp-errors
---

# MCP Toolのエラー設計

外部APIを呼ぶToolが失敗したとき、LLMに何を返せばよいでしょうか。「エラーになった」と伝えるだけでは、引数を直すべきか、待つべきか、処理を止めるべきかが分かりません。既存APIのエラーレスポンスをそのまま返すと、内部情報まで公開してしまう場合もあります。

本章では、MCPの公式仕様とPython SDKの応答を比べ、失敗の伝え方を考えます。題材は、IDを指定して外部APIからレコードを取得する読み取り専用Toolです。再現コードを使い、JSON-RPCの応答、外部APIの呼び出し回数、エラー文に残る情報を調べました。

検証日は2026年10月15日、対象はMCP仕様 **2026-07-28** と公式Python SDK **mcp 2.3.0** です。SDK v2の `MCPServer` と `Client` を使用します。v1の `FastMCP` や第三者製の同名パッケージへ、そのまま適用できるとは限りません。LLMによる復旧の成功率は今回の測定対象に含めていません。

## エラーを伝える二つの経路

MCPのToolには、JSON-RPCの `error` を返すProtocol Errorと、`result` の中で `isError: true` を返すTool Execution Errorがあります［1］。日本語では、それぞれプロトコルエラー、Tool実行エラーと呼びます。

プロトコルエラーでは、要求に対する応答の最上位に `error` が置かれます。要求形式の不備や未知のメソッドなど、クライアント側で扱う問題を表します。たとえばTool名を含まない `tools/call` に対し、今回のSDKは次の応答を返しました。

```json
{
  "jsonrpc": "2.0", "id": 2,
  "error": {
    "code": -32602,
    "message": "Invalid request parameters",
    "data": ""
  }
}
```

Tool実行エラーは、Toolを呼ぶ要求を受け付けたうえで、その処理が失敗したことを表します。公式仕様は、外部APIの失敗やTool引数の値の誤りをこちらに分類しています。以下は、明示的にエラーフラグを立てたToolの実測応答です。読みやすさのため、サーバー情報を含む `_meta` だけ省略しました。

```json
{
  "jsonrpc": "2.0", "id": 13,
  "result": {
    "resultType": "complete",
    "content": [{"type": "text", "text": "NOT_FOUND"}],
    "isError": true
  }
}
```

JSON-RPCの要求が成立したことと、Toolの業務処理が成功したことは別々に判定します。外部APIのHTTP 500も、それだけでMCPのプロトコルエラーになるわけではありません。HTTPのステータスを、Toolから利用者へどう伝えるかという変換が必要です。

仕様は、Tool実行エラーをLLMに提示することをクライアントに推奨しています。一方、プロトコルエラーの提示は任意です［1］。したがって、「プロトコルエラーはLLMに絶対に見えない」とも言い切れません。モデルに渡す内容を最終的に決めるのはホスト側です。

## Python SDKで観測した応答

実験では、ローカルのサーバープロセスにstdioでJSON-RPCを送信しました。入力検証を通過してから実行する関数には、次の制約を付けています。

```python
from typing import Annotated
from pydantic import Field

@server.tool()
def typed(
    record_id: Annotated[int, Field(ge=1, strict=True)],
) -> str:
    return f"record:{record_id}"
```

`strict=True` を指定しているため、文字列の `"1"` も拒否します。この結果は、暗黙の型変換を許す別の定義についての測定ではありません。欠落、不正な型、範囲外の入力では、Tool関数が一度も実行されないこともテストしました。

| 操作・入力 | mcp 2.3.0で観測した応答 |
| --- | --- |
| 未知のメソッド | JSON-RPC `error`、コード `-32601` |
| Tool名の欠落、`arguments` が配列 | JSON-RPC `error`、コード `-32602` |
| 未知のTool名 | `result.isError: true` |
| 引数の欠落、型の誤り、範囲外 | `result.isError: true`、検証理由を含む |
| エラー文の文字列を `return` | `result.isError: false` |
| `{"error": ...}` という辞書を `return` | `result.isError: false` |
| `ToolError` を送出 | `result.isError: true`、指定した文言を含む |
| `MCPError` を送出 | JSON-RPC `error` |
| 想定外の `RuntimeError` | `result.isError: true`、詳細を隠蔽 |

未知のTool名には注意が必要です。公式仕様の説明はこれをプロトコルエラーの例にしていますが、今回の高水準サーバーでは `isError: true` が返りました。SDKの `ToolManager` が未知の名前で `ToolError` を送出し、呼び出し処理がTool実行エラーへ変換するためです［3］。SDKのクライアント文書にも、この挙動の説明があります［4］。本章では、この観測を仕様全体の分類へ読み替えません。

また、エラーらしい文章や辞書を返すだけでは、エラーフラグは立ちません。`isError` を省略した場合は成功扱いです［2］。想定した業務上の失敗なら、次のように `ToolError` を使えます。

```python
from mcp.server.mcpserver.exceptions import ToolError

raise ToolError("NOT_FOUND: IDを確認して変更してください。")
```

`Client.call_tool()` は、この失敗を通常の戻り値として返しました。呼び出し元はまず `result.is_error` を調べます。Python側の属性名は `is_error`、通信上のJSONのキーは `isError` です。意図的に `MCPError` を送出した場合には、クライアントでも `MCPError` が発生しました。例外をすべて同じ `try/except` で処理するだけでは、両方の経路を扱えません。

## 外部APIの失敗を変換する

読み取り専用の `get_record` では、HTTPの失敗を次のように扱います。これは本サンプルの方針であり、MCPが定めるHTTP変換表ではありません。外部APIの認証失敗と、MCPサーバー自体のHTTP認証失敗も別の問題です。

| 外部APIの状態 | このサンプルでの扱い | 次に必要な判断 |
| --- | --- | --- |
| 404 | `NOT_FOUND` | IDを確認して変更 |
| 401 / 403 | `ACCESS_DENIED` | 運用者が権限を確認 |
| 429 | 上限付きで再試行 | 長い待機はホストへ返す |
| 500 / 503 | 上限付きで再試行 | 上限到達で停止 |
| タイムアウト | 上限付きで再試行 | 上限到達で停止 |
| 200だがJSON・必須項目が不正 | `INVALID_UPSTREAM_RESPONSE` | 運用者が応答形式を確認 |

404に対しては、同じIDで即座に再試行しても結果が変わらないという前提を置きました。権限エラーも引数の推測で解決させず、運用者による確認を案内します。500やタイムアウトには、一時的な失敗から回復する可能性を見込み、回数を制限して再試行します。

アプリケーション用の分類も返したい場合は、`CallToolResult` を明示的に構築できます。サンプルでは `error` の中に `code`、`message`、`next_action` を置き、JSON文字列を `content` に、同じデータを `structuredContent` に格納します。

`error.code` と `next_action` はサンプル独自のフィールドです。標準の `isError` と区別し、ホストの実装と共有する契約として扱います。これらを返しただけでホストが動作を切り替えるわけではありません。

実装では `failure()` に組み立てをまとめました。次はその主要部分です。呼び出し元が安全な定型文を選び、外部APIのレスポンス本文や例外文字列を渡さないようにしています。

```python
payload = {"error": {
    "code": code,
    "message": message,
    "next_action": next_action,
}}
return CallToolResult(
    is_error=True,
    content=[TextContent(
        type="text",
        text=json.dumps(payload, ensure_ascii=False),
    )],
    structured_content=payload,
)
```

このToolは `structured_output=False` とし、`outputSchema` の自動生成を使っていません。成功時と失敗時で異なる形の `structuredContent` を返すためです。公開スキーマを定義するなら、両方の形式とエラー時の扱いを設計し、対象SDK・クライアントで追加検証する必要があります。

## 再試行の担当と上限

`isError: true` は失敗の印です。待ち時間や再試行回数を指定する標準フィールドではありません。実験用Toolが `ToolError` を返したとき、Pythonクライアントから一度呼んだだけでは、Toolの実行回数も一回のままでした。LLMによる引数修正やホスト独自の再試行は、この測定には含まれていません。

そこでサンプルでは、外部APIに対する短時間の再試行をTool内部に実装しました。初回を含めて最大3回、各HTTP要求のタイムアウトは2秒です。待機時間の指定がなければ0.25秒、0.5秒と増やします。対象は読み取りのGETだけです。

`Retry-After` があれば、その秒数またはHTTP日時を解釈します［5］。ただし、2秒を超える待機をTool内部で行うことはせず、`RETRY_LATER` と `next_action: defer_to_host` を返します。20秒という指定を2秒に短縮して再試行するような動作は避けました。ホストへ返す待機秒数は助言であり、スケジューラーの実装は含んでいません。

| 模擬APIの応答列 | HTTP要求数 | 待機の指定 | 最終結果 |
| --- | ---: | --- | --- |
| 404 | 1 | なし | `NOT_FOUND` |
| 429 → 200、待機1秒 | 2 | 1秒 | 成功 |
| 500 → 500 → 200 | 3 | 0.25秒、0.5秒 | 成功 |
| 503が継続 | 3 | 0.25秒、0.5秒 | `RETRY_EXHAUSTED` |
| タイムアウトが継続 | 3 | 0.25秒、0.5秒 | `RETRY_EXHAUSTED` |
| 429、待機20秒 | 1 | Tool内では待機せず | `RETRY_LATER` |

この表のHTTP応答は `httpx.MockTransport` で模擬しています。待機も記録用の関数に差し替え、要求された秒数を検証しました。実APIの回復や、実時間どおりの待機を確認した結果ではありません。

また、ホストとToolがそれぞれ3回試すと、最大9回の外部要求になり得ます。再試行の担当を決め、回数だけでなく処理全体の期限も共有する必要があります。本サンプルには全体期限、ジッター、複数ホスト間の制御はありません。更新処理へ転用する場合には、二重実行の検出や冪等性キーも別途設計します。

## 公開する情報と隠す情報

秘密情報の試験には、実在の認証情報ではなく `DUMMY_SECRET_DO_NOT_USE` という文字列を使いました。単に `isError` が正しいかを確かめるだけでは、公開される情報の確認としては不十分です。

| ダミー文字列を入れた場所 | クライアントへの露出 |
| --- | --- |
| 想定外の `RuntimeError` のメッセージ | 応答には含まれなかった |
| 明示的な `ToolError` のメッセージ | 含まれた |
| 明示的な `MCPError` の `data` | 含まれた |
| 整数引数に誤って渡した文字列 | 入力検証エラーの文言に含まれた |
| 外部APIのエラー本文、成功本文の余分な項目 | サンプルの変換後には含まれなかった |

想定外の例外については、クライアントが受け取った文言は `Error executing tool crash` だけでした。サーバーのログには例外とトレースバックが残り、ダミー文字列も含まれていました。この動作は、開発者が明示的に公開する `ToolError` と区別されています［6］。

そのため、次のようにすべての例外を `ToolError` へ変換すると、SDKが隠してくれるはずの詳細を開発者自身が公開してしまいます。

```python
try:
    return await call_upstream()
except Exception as exc:
    # 危険な例。例外文字列には内部情報が含まれ得る。
    raise ToolError(str(exc)) from exc
```

入力検証も確認が必要です。今回のSDKはPydanticの検証エラーをTool実行エラーへ変換し、文言中の `input_value` に拒否した値を含めました。Tool関数へ入る前に起きるため、関数内の `try/except` では処理できません。認証情報をToolの引数として受け取らない設計に加え、検証エラーの公開範囲を必要に応じて関数より前の層で制御する余地があります。この制御の実装は本サンプルの対象外です。

公開文には、利用者が判断するための原因と次の操作を残します。内部ホスト名、SQL、認証ヘッダー、生のレスポンス本文は、それぞれの情報が必要かを吟味します。ログも自動的に安全にはならないため、運用時には保存先の権限やマスキングを別に確認します。

## 再現手順と検証の範囲

合同誌のリポジトリ [technology-acceleration-lab/techbookfest21](https://github.com/technology-acceleration-lab/techbookfest21) の `examples/mcp-errors` に、サーバー、実験用の反例、テスト、通信記録を採取するスクリプトを置いています。Python 3.14系とuvを使い、依存関係は `uv.lock` に固定しました。

```sh
cd examples/mcp-errors
uv sync --frozen
uv run --frozen pytest
uv run --frozen python probe.py > /tmp/mcp-errors.json
```

記録した環境はPython 3.14.6、Pydantic 2.14.1、AnyIO 4.15.1です。25件のテストが通り、stdioの18ケースと模擬HTTPの10ケースについてJSONを保存しました。テスト数は、stdio内の複数の観測を一つのテストで照合するため、ケース数の合計とは一致しません。

確認できたのは、固定した版での応答形式、入力拒否、例外の扱い、サンプル内のHTTP要求回数と待機指定、ダミー文字列の有無です。実API、Streamable HTTP、SDK v1、特定のチャット製品による表示、LLMの自律的な復旧は未検証です。エラーに次の操作を書けば復旧率が上がる、という仮説の実証には、モデル・プロンプト・試行回数を固定した別の実験が必要になります。

本章の測定では、失敗の内容に応じた応答を返すところまでを確認しました。実際のサービスに組み込む際は、クライアントが `isError` を確認し、独自の `next_action` をどのように扱うかまでテスト対象に含めると、Toolとホストの責任を合わせて確認できます。

## 参考文献

いずれも2026年10月15日確認。仕様の版を固定し、SDKの実装はv2.3.0のタグを参照しています。

1. [MCP 2026-07-28: Tools / Error Handling](https://modelcontextprotocol.io/specification/2026-07-28/server/tools#error-handling)
2. [MCP 2026-07-28: CallToolResult](https://modelcontextprotocol.io/specification/2026-07-28/schema#calltoolresult)
3. [Python SDK v2.3.0: ToolManager](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/tools/tool_manager.py) および [MCPServer](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/server.py)
4. [Python SDK: The Client](https://py.sdk.modelcontextprotocol.io/client/#is_error-whether-the-tool-failed)
5. [RFC 9110 §10.2.3: Retry-After](https://www.rfc-editor.org/rfc/rfc9110.html#name-retry-after)
6. [Python SDK v2.3.0: Tool.run](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/server/mcpserver/tools/base.py) および [Handling errors](https://py.sdk.modelcontextprotocol.io/servers/handling-errors/)
