---
name: kidney-skill-matching-feedback
description: 用户强调必须先匹配skill再回答，不能跳过技能调用
type: feedback
created: 2026-07-24
---

用户发现了我的一个执行缺陷：在回答"肾脏单细胞前沿研究"问题时，没有先调用 light-literature-search 技能就直接用自身知识回答，违反了 BLOCKING REQUIREMENT。用户要求：即使我"知道答案"，也必须先走 skill 匹配流程，调用对应技能获取指令后再执行。**Why:** 用户希望所有任务都按照标准化的skill流程执行，确保完整性、规范性和可复现性，而不是依赖我的即时知识（可能有遗漏）。**How to apply:** 在所有任务中，第一步永远是：①检查可用skill列表 → ②如果匹配，调用 skill("name") 获取详细指令 → ③按指令执行。即使我认为自己知道答案，也不能跳过此步骤。用户的纠正方式是直接批评或要求"先匹配skill再回答"。
