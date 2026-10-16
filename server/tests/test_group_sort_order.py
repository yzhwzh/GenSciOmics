#!/usr/bin/env python3
"""B45 回归测试：条件/分组标签的排序。

背景（2026-10-16）：40425564.STGD 的 `Group` 是 int64 的分化天数 40/90/150/200/260。
B43 把图修得能画出来之后，横轴/图例的顺序暴露出来是**字典序**的：

    150, 200, 260, 40, 90

根因在 `utils.cond_sort_key`：它只做了「control 排最后 + 其余按字典序」，从没看过
数字。这条**排序**规则在仓库里被手写了 **8 遍**（`plots.py` 5 处内联 lambda、
`stats.py` 2 处、`bulk.py` 1 处分身），其中几处内联 lambda **没有次级键**，并列项
按 `set` 迭代序，顺序本身就不确定。

修法：把规则收敛成 `utils.cond_sort_key` 一份 —— 数字按数值升序、非数字次之、
control 最后 —— 其余全部改为调用它。另有 6 处只判断「是否 control」而**不排序**
的（`build_cond_palette` 与本文件覆盖不到的取色逻辑），同样收敛到 `utils.is_control`。

**关键约束（用户明确要求）：control 排最后的逻辑不变。** 所以 control 判定必须
**优先于**数字判定，否则 `Control2` 会因为含数字被分到数字组排到最前。本文件
`test_control_with_digit_still_last` 锁住的就是这一点。

运行：python3 server/tests/test_group_sort_order.py
项目未引入 pytest，故为自包含脚本；任一断言失败则退出码非 0。
"""
from __future__ import annotations

import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

from analysis.utils import cond_sort_key
import analysis.bulk as bulk

PASS: list[str] = []
FAIL: list[str] = []


def check(cond: bool, msg: str) -> None:
    (PASS if cond else FAIL).append(msg)
    print(('  ✓ ' if cond else '  ✗ ') + msg)


def order(labels: list[str]) -> list[str]:
    return sorted(labels, key=cond_sort_key)


def _old_key(name: str) -> tuple:
    """改造前的实现，仅用于「不含数字的标签行为不变」这条等价性对照。"""
    ln = name.lower()
    is_ctrl = any(k in ln for k in ('control', 'normal', 'healthy'))
    return (1 if is_ctrl else 0, name)


# ── 1. 本次要修的：数字按数值升序 ────────────────────────────────────────

def test_numeric_labels_ascend() -> None:
    """天数 40/90/150/200/260 必须按数值排，不能按字典序。"""
    got = order(['150', '200', '260', '40', '90'])
    check(got == ['40', '90', '150', '200', '260'],
          f'天数应按数值升序 (实际 {got})')
    # 把「字典序」这个错误答案也钉住，防止有人退回旧实现还以为过了
    check(got != sorted(['150', '200', '260', '40', '90']),
          '不得等于字典序结果（那正是要修的 bug）')


def test_single_digit_and_multi_digit_mix() -> None:
    """1..12 这种要按数值，不是 1,10,11,12,2,..."""
    labels = [str(i) for i in range(1, 13)]
    got = order(list(reversed(labels)))
    check(got == labels, f'1..12 应按数值升序 (实际 {got[:6]}...)')


def test_number_embedded_in_text() -> None:
    """`1 month`/`6 months`/`12 months` 取第一段数字排序。"""
    got = order(['12 months', '1 month', '6 months'])
    check(got == ['1 month', '6 months', '12 months'],
          f'月数应按数值升序 (实际 {got})')


# ── 2. 用户的硬约束：control 最后（且对无数字标签逐字不变） ──────────────

def test_disease_before_control() -> None:
    got = order(['Control', 'Disease'])
    check(got == ['Disease', 'Control'], f'Disease 在 Control 前 (实际 {got})')


def test_control_variants_all_last() -> None:
    """control / normal / healthy 三个关键词都算对照，都排最后。"""
    got = order(['Healthy', 'Disease', 'Normal', 'Treatment', 'Control'])
    check(set(got[-3:]) == {'Healthy', 'Normal', 'Control'},
          f'三个对照词都应在最后 3 位 (实际 {got})')
    check(set(got[:2]) == {'Disease', 'Treatment'},
          f'非对照在前 2 位 (实际 {got})')


def test_control_with_digit_still_last() -> None:
    """**这条就是本文件存在的理由。**

    `Control2` 含数字。若先判数字再判 control，它会落进数字组排到**最前**，
    "control 最后" 就被破坏了。control 判定必须优先。
    """
    got = order(['Control2', 'Disease', 'Treatment1'])
    check(got[-1] == 'Control2', f'Control2 必须排最后 (实际 {got})')
    check(got[:2] == ['Treatment1', 'Disease'],
          f'Treatment1(数字组) 在 Disease(非数字组) 前 (实际 {got})')


# ── 3. 混合与边界 ──────────────────────────────────────────────────────

def test_numbers_before_text() -> None:
    got = order(['Disease', '40', 'Control', '90'])
    check(got == ['40', '90', 'Disease', 'Control'],
          f'数字在前、非数字次之、control 最后 (实际 {got})')


def test_nan_label_is_not_numeric() -> None:
    """B43 之后缺失标签会变成字符串 'nan'。它必须走非数字分支。

    `float('nan')` 是能解析成功的，一旦按数字处理，NaN 参与比较恒为 False，
    排序结果就不确定了。这里用正则取数字，'nan' 天然不匹配。
    """
    got = order(['nan', 'B', 'A'])
    check(got == ['A', 'B', 'nan'], f"'nan' 应按字典序排在非数字里 (实际 {got})")


def test_empty_and_single() -> None:
    check(order([]) == [], '空列表返回空列表')
    check(order(['40']) == ['40'], '单元素原样返回')


def test_no_type_error_on_mixed_labels() -> None:
    """元组比较是逐位的，位型不一致会 TypeError（int 与 str 相比）。

    这是这类排序键最容易踩的坑：写成 `(0 if numeric else 1, value_or_name)`
    时，数字位放 int、非数字位放 str，一混合就炸。
    """
    try:
        order(['40', 'Disease', 'Control', '150', 'nan', 'Normal'])
        check(True, '混合标签不抛 TypeError')
    except TypeError as e:
        check(False, f'混合标签抛了 TypeError: {e}')


# ── 4. 不含数字的标签：与改造前逐字等价（"不改变现有行为"的证据） ────────

def test_digit_free_labels_match_old_implementation() -> None:
    cases = [
        ['Control', 'Disease'],
        ['Control', 'Disease', 'Treatment'],
        ['Normal', 'Tumor'],
        ['Healthy', 'COPD', 'IPF', 'ILD'],
        ['Control', 'Normal', 'Healthy'],
        ['A', 'B', 'C'],
    ]
    all_same = True
    for labels in cases:
        new = sorted(labels, key=cond_sort_key)
        old = sorted(labels, key=_old_key)
        if new != old:
            all_same = False
            check(False, f'{labels}: 新 {new} != 旧 {old}')
    if all_same:
        check(True, f'{len(cases)} 组不含数字的标签，新旧实现结果完全一致')


# ── 5. bulk.py 的薄壳确实委托到了同一份实现 ────────────────────────────

def test_bulk_delegates_to_shared_key() -> None:
    labels = ['150', '40', 'Control', '90']
    check(bulk._group_sort_key('40') == cond_sort_key('40'),
          'bulk._group_sort_key 与 cond_sort_key 对同一输入结果一致')
    check(sorted(labels, key=bulk._group_sort_key) ==
          sorted(labels, key=cond_sort_key),
          'bulk 的排序结果与共享实现一致（不再是第二份副本）')


TESTS = (
    test_numeric_labels_ascend,
    test_single_digit_and_multi_digit_mix,
    test_number_embedded_in_text,
    test_disease_before_control,
    test_control_variants_all_last,
    test_control_with_digit_still_last,
    test_numbers_before_text,
    test_nan_label_is_not_numeric,
    test_empty_and_single,
    test_no_type_error_on_mixed_labels,
    test_digit_free_labels_match_old_implementation,
    test_bulk_delegates_to_shared_key,
)


def _unregistered() -> list[str]:
    """定义了却没登记进 TESTS 的用例 —— 静默跳过的测试比没有测试更坏。"""
    declared = {n for n, v in globals().items()
                if n.startswith('test_') and callable(v)}
    return sorted(declared - {t.__name__ for t in TESTS})


def main() -> int:
    print('B45 regression: 分组标签排序（数字按数值、control 仍最后）\n')

    missing = _unregistered()
    if missing:
        FAIL.append(f'未登记的用例: {missing}')
        print(f'  ✗ 有用例定义了却没进 TESTS: {missing}\n')

    for t in TESTS:
        print(f'[{t.__name__}]')
        try:
            t()
        except Exception:
            import traceback
            FAIL.append(f'{t.__name__} raised')
            print('  ✗ 异常:\n' + traceback.format_exc())
        print()

    print(f'PASS {len(PASS)} / FAIL {len(FAIL)}')
    if FAIL:
        for m in FAIL:
            print('  FAILED:', m)
        return 1
    print('ALL B45 CHECKS PASSED')
    return 0


if __name__ == '__main__':
    sys.exit(main())
