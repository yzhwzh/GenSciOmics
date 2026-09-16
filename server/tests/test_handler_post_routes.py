#!/usr/bin/env python3
"""POST 分发层的回归测试。

背景：`/api/drug/pipeline/stream` 上线时，路由注册了、入参校验写了、单元测试
也全绿 —— 但端到端一跑就永远报 `query required`。原因不在这些地方，而在
`handler.py:do_POST` 的一个手维护名册 `is_json_body`：不在册的 POST 路由拿到的
是 query string 字典（通常为空），而不是解析好的 JSON body。

为什么此前没测出来：`test_drug_stages.py` 直接调 `handle_drug_pipeline_stream(h, data)`，
把 body 当参数喂进去，**绕过了分发层**。所以这里必须走真实 HTTP —— 只有真实
`do_POST` 才会暴露名册漏登记。

两个断言各有分工：
  [1] 静态：遍历 ROUTES 里每条 POST，断言分发层确实会把 body 交给它。
      这条是为**下一个**新端点准备的 —— 漏登记会在这里红，而不是等到线上。
  [2] 动态：真起一个 ThreadingHTTPServer 打真实请求，用「校验报的是哪条错」
      反推 body 到底有没有到达 handler。这条抓的是「规则写对了但没生效」。

无 pytest，失败退出码非 0（与 server/tests/ 下其它脚本一致）。
"""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from handler import APIHandler, post_route_delivers_json_body   # noqa: E402
from routes import ROUTES                                       # noqa: E402

PASS: list[str] = []
FAIL: list[str] = []


def check(label: str, cond: bool, detail: str = '') -> None:
    if cond:
        PASS.append(label)
        print(f'  ✓ {label}' + (f'  ({detail})' if detail else ''))
    else:
        FAIL.append(label)
        print(f'  ✗ {label}  {detail}')


# ── [1] 静态：ROUTES 里每条 POST 都必须被分发层覆盖 ────────────────────
# 关键：调的是 handler 里**真正在跑的那个函数**，不是这里抄的一份规则。
# 抄一份的话，它永远陪着自己写的规则，发现不了它与 handler 的漂移 ——
# 第一版就是这么写的，回退到修复前的 handler 时它照样报「8/8 覆盖」。
def test_static_route_coverage() -> None:
    print('\n[1] 静态：ROUTES 中每条 POST 路由都会被分发层喂 JSON body')
    post_routes = sorted(p for (method, p) in ROUTES if method == 'POST')
    check('ROUTES 里确实有 POST 路由', len(post_routes) > 0, f'{len(post_routes)} 条')

    uncovered = [p for p in post_routes if not post_route_delivers_json_body(p)]
    check(
        '没有「登记了路由却拿不到 body」的 POST 端点',
        not uncovered,
        f'漏登记：{uncovered} —— 需要同步更新 handler.py:do_POST 的 is_json_body'
        if uncovered else f'覆盖 {len(post_routes)}/{len(post_routes)}',
    )


# ── [2] 动态：真打一个 HTTP 请求，看 body 是否真的到了 handler ──────────
def _post(port: int, path: str, payload: dict) -> tuple[int, dict]:
    req = urllib.request.Request(
        f'http://127.0.0.1:{port}{path}',
        data=json.dumps(payload).encode(),
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status, json.loads(r.read().decode('utf-8', 'replace'))
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', 'replace')
        try:
            return e.code, json.loads(raw)
        except json.JSONDecodeError:
            return e.code, {'raw': raw[:200]}


def test_real_dispatch() -> None:
    print('\n[2] 动态：真实 HTTP 请求，body 确实到达 handler')
    # 端口 0 = 让内核分配空闲端口，避免和开发中的 :6001 撞车。
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), APIHandler)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        # 判别器：带 query、**不带** stage_ids。
        #   body 到达 → 走到第二条校验 → "stage_ids required"
        #   body 没到 → data 是 {} → 第一条就挂 → "query required"
        # 两条错误信息不同，所以这一发足以区分分发层的好坏，且不会真的调到 LLM。
        status, body = _post(port, '/api/drug/pipeline/stream', {'query': 'EGFR'})
        err = body.get('error', '')
        check(
            '带 query 的请求被识别为「缺 stage_ids」而非「缺 query」',
            'stage_ids' in err,
            f'HTTP {status} error={err!r}',
        )

        # 反面：body 真的缺 query 时，仍要正确报 query required。
        # 否则上面那条可能只是因为校验顺序被改过而「碰巧」通过。
        status, body = _post(port, '/api/drug/pipeline/stream', {})
        check(
            '空 body 仍报 query required（证明校验顺序未被改动）',
            body.get('error') == 'query required',
            f'HTTP {status} error={body.get("error")!r}',
        )

        # query string 里的参数不该被当成 body 用 —— 分发层现在给的是 body，
        # 所以 ?query=EGFR 不应该让校验通过。
        status, body = _post(port, '/api/drug/pipeline/stream?query=EGFR&stage_ids=target', {})
        check(
            'query string 不再被当作参数来源',
            body.get('error') == 'query required',
            f'HTTP {status} error={body.get("error")!r}',
        )
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=5)


def main() -> int:
    print('=' * 62)
    print('handler.do_POST 分发层测试')
    print('=' * 62)
    test_static_route_coverage()
    test_real_dispatch()

    print('\n' + '=' * 62)
    print(f'PASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        print('失败项：')
        for f in FAIL:
            print(f'  - {f}')
        return 1
    print('ALL post-route dispatch CHECK PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
