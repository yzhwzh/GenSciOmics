#!/usr/bin/env python3
"""real_path 白名单的路径穿越守卫。

自包含（不依赖 pytest），沿用 server/tests/test_results_dir.py 的骨架：
每条断言打一行 PASS/FAIL，末尾 sys.exit(1) 表明有失败。

运行：python3 server/tests/test_real_path_traversal.py

为什么要有这个文件：
`routes.validate_real_path` 声称「校验路径在 DATA_DIRS 之内」（CLAUDE.md 设计决策 #3）。
它用 `Path(path_str).is_relative_to(d)` 做判断 —— 但 `is_relative_to` 是**纯词法**比较，
**不折叠 `..`**：

    Path('<root>/Data/../server/config.py').is_relative_to('<root>/Data')  →  True

而函数返回的是**未折叠的原始路径**（有意如此，见下），随后 OS 把 `..` 解析掉，
白名单就失效了。第 1 组断言是这条回归：改前必须 FAIL。

注意与 test_results_dir.py 的分工：那里测的是 `_safe_results_path`（`/api/results`
端点，先 resolve 再断言，是正确的），这里测的是 `validate_real_path`（约 20 个
数据端点共用）。两道校验并列存在，别以为测过一个就等于测了另一个。

第 2 组断言守的是**不能修过头**：
函数故意校验「未 resolve」的路径，是为了放行 `Data/` 内指向外部存储的软链接
（`Data/` 整个目录就是一整片软链接，指向 /data/... 下的真实数据）。
所以修法只能用 `os.path.normpath()`（只词法折叠 `..`，不碰软链接），
**不能用 `.resolve()`** —— 那会把软链接一并禁掉，整个平台读不到任何数据。
第 2 组断言就是防止后来者「顺手改成 resolve」。
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_fail = 0


def check(label: str, cond: bool, detail: str = '') -> None:
    global _fail
    if cond:
        print(f'  PASS  {label}')
    else:
        _fail += 1
        print(f'  FAIL  {label}' + (f'  — {detail}' if detail else ''))


import config                                      # noqa: E402
from routes import validate_real_path              # noqa: E402

DATA = config.PROJECT_ROOT / 'Data'


# ── 1. 词法 `..` 穿越必须被拒 ──────────────────────────────────────────
print('\n[1] Data/../… 折叠后落在白名单外的路径必须被拒（回归：改前放行）')

# 逃逸目标要真实存在，否则 `is_file()` 会先挡掉，测不到词法检查那一步 ——
# 那样这条断言会「因为错误的原因通过」。前置断言把这件事挑明。
_ESCAPE_TARGET = config.PROJECT_ROOT / 'server' / 'config.py'
check('前置：逃逸目标确实存在（否则测的是 is_file 而非词法检查）',
      _ESCAPE_TARGET.is_file(), f'{_ESCAPE_TARGET} 不存在')

for _label, _path in [
    ('单层 ..',         DATA / '..' / 'server' / 'config.py'),
    ('深层 ..',         DATA / 'Human' / '..' / '..' / 'server' / 'config.py'),
    ('.. 折回后再出去', DATA / '..' / 'server' / '..' / 'server' / 'config.py'),
]:
    _s = str(_path)
    _got = validate_real_path(_s)
    check(f'{_label}：{_s[len(str(config.PROJECT_ROOT)):]} 被拒',
          _got is None, f'放行了，返回 {_got}')

# normpath 之后仍在白名单内的 .. 应当**继续放行** —— 否则就是一刀切禁掉 `..`，
# 那会误伤合法路径（例如前端某天传了个未规范化的 Data/Human/../Human/x.h5ad）。
_probe = next((p for p in (DATA / 'Human').rglob('*') if p.is_symlink() and p.is_file()), None)
if _probe is not None:
    _rel = _probe.relative_to(DATA / 'Human')
    _normalized = str(DATA / 'Human' / '..' / 'Human' / _rel)
    check('折叠后仍在 Data/ 内的 .. 路径继续放行',
          validate_real_path(_normalized) is not None,
          f'{_normalized} 被误拒')
else:
    print('  SKIP  折叠后仍在 Data/ 内 —— Data/Human 下没找到可用软链接')


# ── 2. Data/ 内指向外部的软链接必须继续放行（防「顺手改成 resolve」）──
print('\n[2] Data/ 内的软链接仍须放行（这是刻意保留的设计，别修过头）')

_link = next((p for p in DATA.rglob('*') if p.is_symlink() and p.is_file()), None)
if _link is None:
    check('前置：Data/ 下存在可用软链接', False, '找不到任何软链接，本组断言无法执行')
else:
    _target = Path(os.path.realpath(_link))
    check('前置：该软链接确实指向 Data/ 之外',
          not _target.is_relative_to(DATA),
          f'指向 {_target}，反而在 Data/ 内，本组断言失去意义')
    check(f'软链接放行：{_link.relative_to(config.PROJECT_ROOT)}',
          validate_real_path(str(_link)) is not None,
          '被拒了 —— 说明有人把它改成 resolve() 了，整个平台会读不到数据')


# ── 3. 边界情形 ────────────────────────────────────────────────────────
print('\n[3] 边界')

check('空串被拒', validate_real_path('') is None)
check('None 被拒', validate_real_path(None) is None)
check('不存在的路径被拒', validate_real_path(str(DATA / 'NoSuchFile.h5ad')) is None)
check('Data/ 目录本身被拒（要求是文件）', validate_real_path(str(DATA)) is None)
check('白名单外的普通文件被拒',
      validate_real_path(str(config.PROJECT_ROOT / 'README.md')) is None)


# ── 4. 前提：Data/ 下不得有目录软链接 ──────────────────────────────────
print('\n[4] 前提断言：Data/ 下只能有文件软链接')

# 为什么这条前提必须被测：validate_real_path 用的是 os.path.normpath，那是**词法**
# 折叠 —— `Data/<目录软链>/../x` 词法折叠成 `Data/x`（落在白名单内、放行），
# 而 OS 实际解析是「先跟软链到目标目录、再退一级」，落点在 Data/ 之外。
# 也就是说：**一旦 Data/ 下出现目录软链接，第 1 组修好的洞会以另一种形式重新打开。**
#
# 当前 97 个软链接全是文件链接、无一目录链接，所以这条路走不通。但「碰巧走不通」
# 不是安全边界。这条断言把前提摆到明面上：布局一变，这里先红，并指向 routes.py。
_dir_links: list[Path] = []
_file_link_n = 0
for _root, _dirs, _files in os.walk(DATA, followlinks=False):
    for _n in _dirs:
        _p = Path(_root) / _n
        if _p.is_symlink():
            _dir_links.append(_p)
    for _n in _files:
        if (Path(_root) / _n).is_symlink():
            _file_link_n += 1

check('Data/ 下不存在目录软链接（有则须重新审视 validate_real_path 的词法折叠）',
      not _dir_links,
      f'发现 {len(_dir_links)} 个目录软链接，例如 {[_p.relative_to(config.PROJECT_ROOT) for _p in _dir_links[:3]]}')
check('前置：Data/ 下确实存在文件软链接（否则第 2 组断言形同虚设）',
      _file_link_n > 0, f'只找到 {_file_link_n} 个文件软链接')
print(f'  （当前：文件软链接 {_file_link_n} 个，目录软链接 {len(_dir_links)} 个）')


print()
if _fail:
    print(f'{_fail} 项失败')
    sys.exit(1)
print('ALL PASS')
