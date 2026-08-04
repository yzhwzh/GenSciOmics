"""SkillTool — 调用 SKILL.md 技能。对标 Claude Code 的 src/tools/SkillTool/。"""
from __future__ import annotations
import re
from pathlib import Path
from skills import register_skill, ParamDef, get_skill, get_skill_content, SKILL_REGISTRY

SKILLTOOL_PROMPT = """Execute a skill within the main conversation

When users ask you to perform tasks, check if any of the available skills match. Skills provide specialized capabilities and domain knowledge.

IMPORTANT:
- Available skills are listed in system prompt's "可用技能" section
- When a skill matches the user's request, this is a BLOCKING REQUIREMENT: invoke the relevant skill tool BEFORE generating any other response about the task
- NEVER mention a skill without actually calling this tool
- Do not invoke a skill that is already running
- If you see a <command-name> tag in the current conversation turn, the skill has ALREADY been loaded — follow the instructions directly instead of calling this tool again"""

SKILLS_DIR = Path(__file__).resolve().parent.parent.parent / 'skills'


def skill(name: str, args: str = '') -> dict:
    sd = get_skill(name)
    content = get_skill_content(name)
    if not content:
        return {'error': f'Skill not found: {name}',
                'available_skills': [s.name for s in SKILL_REGISTRY.values() if s.func is None]}

    # Inject base directory (Claude Code pattern: "Base directory for this skill: <dir>")
    skill_dir = SKILLS_DIR / name
    if skill_dir.is_dir():
        base_dir_line = f"Base directory for this skill: {skill_dir}\n\n"
        content = base_dir_line + content
        # Replace ${CLAUDE_SKILL_DIR} with actual path
        content = content.replace('${CLAUDE_SKILL_DIR}', str(skill_dir))

    return {'name': name, 'description': sd.description if sd else '', 'content': content, 'args_passed': args}

register_skill(name='skill', description=SKILLTOOL_PROMPT,
               params=[ParamDef(name='name', type='string', description='技能名称'),
                       ParamDef(name='args', type='string', description='参数', required=False)])(skill)
