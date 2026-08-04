#!/usr/bin/env python3
"""SKILL.md 加载器 — 像 Claude Code 一样自动扫描和解析技能文件。"""
from __future__ import annotations
import re
from pathlib import Path
from skills import SKILL_REGISTRY as _SK_REG

SKILLS_DIR = Path(__file__).parent


def parse_frontmatter(text: str) -> dict:
    """解析 SKILL.md 的 YAML frontmatter"""
    m = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
    if not m:
        return {}
    meta = {}
    for line in m.group(1).strip().split('\n'):
        if ':' in line:
            k, _, v = line.partition(':')
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta


_skills_cache: list[dict] | None = None

def scan_skills() -> list[dict]:
    """扫描 skills/*/SKILL.md，返回结构化列表（带缓存）"""
    global _skills_cache
    if _skills_cache is not None:
        return _skills_cache
    skills = []
    for entry in sorted(SKILLS_DIR.iterdir()):
        skill_md = entry / 'SKILL.md'
        if not skill_md.is_file():
            continue
        text = skill_md.read_text(encoding='utf-8')
        meta = parse_frontmatter(text)
        scripts_dir = entry / 'scripts'
        skills.append({
            'name': meta.get('name') or entry.name,
            'description': meta.get('description') or '',
            'instructions': text,
            'scripts_dir': str(scripts_dir) if scripts_dir.is_dir() else None,
            'folder': entry.name,
        })
    # Also include registered function-based skills (no SKILL.md)
    for sname, sdef in sorted(_SK_REG.items()):
        if sdef.func and not any(s['name'] == sname for s in skills):
            skills.append({
                'name': sname,
                'description': sdef.description,
                'instructions': None,
                'scripts_dir': None,
                'folder': '',
            })
    _skills_cache = skills
    return skills


def format_skills_for_prompt(skills: list[dict]) -> str:
    """将可用技能格式化为 LLM 可读文本"""
    if not skills:
        return ''
    parts = [
        '\n\n## 可用技能',
        '当用户任务匹配某个技能描述时，调 skill(name="技能名") 获取完整指令执行。',
        '',
    ]
    for s in skills:
        folder = s.get('folder', '')
        if folder and s.get('instructions'):
            parts.append(f'- {s["name"]}: {s["description"] or "无描述"} → 调 skill("{s["name"]}")')
        else:
            parts.append(f'- {s["name"]}: {s["description"] or "无描述"}')
    parts.append('')
    parts.append('选择逻辑：优先匹配最具体的技能描述。如果没有匹配的 skill，再用通用工具。')
    return '\n'.join(parts)

# ── Gene extraction utilities ─────────────────────────────────
import re as _re
GENE_PATTERN = _re.compile(r'(?<![A-Z0-9])([A-Z][A-Z0-9]{2,10}(?:-[A-Z0-9]+)?)(?![A-Z0-9])')
EXCLUDED_WORDS = {"ACE","ACT","AGE","ALL","AND","ANY","ARE","ASK","BOX","BUT","CAN","CAP","CAR","CAT","CELL","CELLS","CODE","CORE","CUT","DEG","DATA","DAY","DID","DOE","DOES","DONE","DOWN","DROP","EACH","EAST","EDGE","ELSE","ENDS","EVEN","FIVE","FOUR","FREE","FROM","FULL","GENE","GENES","GIVE","GOAL","GOOD","GROUP","HALF","HAND","HARD","HAVE","HEAD","HELP","HERE","HIGH","HOLD","HOME","HOUR","HUGE","IDEA","INTO","ITEM","JOIN","JUST","KEEP","KEPT","KIND","KING","KNOW","LAST","LATE","LEAD","LEFT","LESS","LIKE","LINE","LINK","LIST","LIVE","LOAD","LONG","LOOK","LORD","LOSE","LOSS","LOST","LOVE","LUCK","LUNG","MADE","MAIL","MAIN","MAKE","MANY","MARK","MASS","MEAN","MEET","MENU","MILD","MIND","MINE","MISS","MODE","MORE","MOST","MOVE","MUCH","MUST","NAME","NEAR","NEED","NEST","NEW","NEXT","NICE","NINE","NODE","NONE","NOTE","NULL","ONCE","ONLY","ONTO","OPEN","ORAL","OVER","PAGE","PAID","PAIR","PARK","PART","PASS","PAST","PATH","PEAK","PICK","PLAN","PLAY","PLOT","PLUG","PLUS","POOR","PORT","POST","PULL","PUSH","RACE","RANK","RARE","RATE","READ","REAL","RENT","REST","RICE","RICH","RIDE","RING","RISE","RISK","ROAD","ROCK","ROLE","ROLL","ROOM","ROOT","ROPE","RULE","SAFE","SAID","SAME","SAVE","SCAN","SEAL","SEAT","SEED","SEEN","SELF","SELL","SEND","SENT","SET","SHIP","SHOP","SHOT","SHOW","SHUT","SIDE","SIGN","SILK","SING","SINK","SITE","SIZE","SKIP","SLOW","SNAP","SOFT","SOIL","SOME","SONG","SOON","SORT","SOUL","SOUR","SPAN","SPEC","SPIN","SPOT","STAR","STAY","STEM","STEP","STOP","STUB","SUIT","SURE","SWAP","SWIM","TAIL","TAKE","TALK","TALL","TANK","TAPE","TASK","TEAM","TELL","TEND","TENT","TERM","TEST","TEXT","THAN","THAT","THEM","THEN","THIN","THIS","TIDE","TILL","TIME","TINY","TIRE","TOLD","TOLL","TONE","TOOL","TOP","TOUR","TOWN","TRAP","TREE","TRIM","TRIP","TRUE","TUBE","TUNE","TURN","TWIN","TYPE","TYPES","UNDO","UNIT","UPON","VARY","VAST","VEIN","VENT","VERY","VIEW","VINE","VOID","VOTE","WADE","WAIT","WALK","WALL","WANT","WARD","WARM","WARN","WASH","WAVE","WEAK","WEAR","WEED","WEEK","WELL","WENT","WEST","WHAT","WHEN","WHOM","WIDE","WIFE","WILD","WILL","WIND","WINE","WING","WIPE","WIRE","WISE","WISH","WORD","WORK","WORM","WRAP","YARD","YEAR","YELL","ZEAL","ZERO","ZONE","ZOOM"}

def extract_gene(text: str) -> str | None:
    matches = GENE_PATTERN.findall(text.upper())
    candidates = [m for m in matches if len(m) >= 2 and m not in EXCLUDED_WORDS]
    return candidates[0] if candidates else None
