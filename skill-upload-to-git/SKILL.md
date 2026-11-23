---
name: skill-upload-to-git
description: 把 skill 库复刻/同步到目标文件夹，提交并推送到对应 git 仓库。用于用户说"同步 skill 到仓库""把 skill 上传 git""复刻 skill 库""更新 skill 仓库""skill上传git仓库"等场景。默认源为 CC Switch 的 skill 库，默认目标为 D:\My_Program\Ai Work_Space\My Skills。
---

# Skill 上传 Git 仓库

以 git 目标库为唯一编辑起点和真相源：所有 skill / MCP 的修改都直接改 `D:/My_Program/Ai Work_Space/My Skills/`，先提交推送到 git，再**反向分发**到 CC Switch 源库，最后由用户在 CC Switch 里勾选哪些 agent 使用。核心是**git 为真相源 → 推送验证指针 → 反向分发到 CC → 用户勾选投影**。同名文件用源（新版）逐文件覆盖，目标独有的脚本/参考文档保留。

## 三处角色（重要）

| 库 | 角色 | 谁写它 |
|---|---|---|
| **git 目标库** `D:/My_Program/Ai Work_Space/My Skills/` | **唯一编辑起点 + 真相源**，所有 skill/MCP 先在这里改 | 用户/AI 直接改 |
| **CC Switch 源库** `C:/Users/123456/.cc-switch/skills/` | 分发中枢，CC Switch 从这里按勾选投影到各 agent | 由 git 库反向同步过来 |
| **各 agent 本地目录**（如 `~/.workbuddy/skills/`） | 投影产物，不直接改 | CC Switch 自动生成 |

**流程方向**：git 目标库（编辑）→ git 仓库（提交推送）→ CC Switch 源库（反向分发）→ 用户在 CC Switch 勾选 → 投影到各 agent。**不要在 agent 本地目录或 CC 源库直接改文件**，下次分发会被覆盖。

| 角色 | 路径 |
|---|---|
| git 目标库 / 真相源 | `D:/My_Program/Ai Work_Space/My Skills/` |
| CC Switch 源库（分发目标） | `C:/Users/123456/.cc-switch/skills/` |
| MCP 代码真相源 | `<git 目标库>/.mcp-servers/` |
| MCP 代码分发目标 | `C:/Users/123456/.mcp-servers/`（本地运行位置） |
| 目标 git 仓库 | 读目标文件夹的 `git remote -v`（当前 `HilbertJeanAngers/CC-Switch-Skills-Repositorie`） |

用户可覆盖源/目标。CC Switch 登记的 skill 仓库列表在 `C:/Users/123456/.cc-switch/cc-switch.db` 的 `skill_repos` 表（含 owner/name/branch/host）。

`sync_skills.py` 一次跑两组同步：**skill 组**（源根目录 → 目标根目录）和 **mcp 组**（MCP 源 → MCP 目标）。两组用同一套「缺失复制 / 独有保留 / 同名逐文件覆盖」规则，MCP 组额外忽略 `__pycache__` 和 `*.pyc`。`--no-mcp` 可关闭 MCP 组，`--mcp-source` 改 MCP 源、`--mcp-target` 改 MCP 目标。默认方向仍是 CC→git（兼容旧用法）；**新流程反向分发时显式指定 `--source`/`--target`/`--mcp-source`/`--mcp-target`**。

## 流程（新：git 为真相源）

### 1. 在 git 目标库直接编辑

所有 skill / MCP 的修改**直接改 `D:/My_Program/Ai Work_Space/My Skills/` 里的文件**，这是唯一编辑起点。在原本基础上增量改，不推倒重来、不删目标已有文件。

### 2. 精准提交并推送

```bash
cd "D:/My_Program/Ai Work_Space/My Skills"
git add -- <只列出本次实际改动的文件/目录>   # 不用 git add -A
git diff --cached --name-only   # 确认暂存区只有本次改动
git commit -m "<描述本次改动的 message>"
git push origin main
```

**精准提交**：只暂存本次真正改过的文件，改哪个 skill 就只动哪个。

### 3. 推送验证（必做）

本地 `origin/main` 只是缓存引用，**不能只信它**。必须查远端真实指针与本地 HEAD 比对，一致才算成功：

```bash
git ls-remote origin refs/heads/main
git rev-parse HEAD
```

### 4. 反向分发到 CC Switch 源库

git 推送成功后，把 git 目标库的内容**反向同步**到 CC Switch 源库和 MCP 本地运行位置。先 dry-run 看差异，再去掉 `--dry-run` 执行：

```bash
python "D:/My_Program/Ai Work_Space/My Skills/skill-upload-to-git/scripts/sync_skills.py" \
  --source "D:/My_Program/Ai Work_Space/My Skills" \
  --target "C:/Users/123456/.cc-switch/skills" \
  --mcp-source "D:/My_Program/Ai Work_Space/My Skills/.mcp-servers" \
  --mcp-target "C:/Users/123456/.mcp-servers" \
  --dry-run
```

三组差异规则同前：**缺失复制 / 独有保留 / 同名逐文件覆盖同名文件**（`--keep-target` 可反向保留目标旧版）。这一步完成后，**不要**再手动改 `~/.workbuddy/skills/` 等 agent 本地目录。

若只改了 MCP 配置（模板），还要把模板回填到 CC 数据库：见 `MCP_TEMPLATE.md`。

### 5. 用户在 CC Switch 勾选

分发到 CC 源库后，由用户在 CC Switch 界面勾选哪些 skill / MCP 给哪些 agent 用，CC Switch 自动投影到各 agent 本地配置。这一步是用户操作，AI 不代替。

### 6. 报告

说清楚：改了哪些文件、提交了什么、远端指针是否一致、是否已分发到 CC 源库。

## 幂等原则

若第 1 步发现 git 目标库与 CC 源库一致、且 `ls-remote` 哈希与 HEAD 一致，说明早已同步完成——**直接报告现状，不要做无谓的 commit / push / 分发**。

## 注意

- 中文目录名在 git 里正常，不必改成英文
- 推送属于外部动作，若用户只说"复刻/同步"而没说"上传"，做到复刻即可，推送前确认
- 目标若还不是 git 仓库，先问用户要哪个远端仓库，再 `git init` + `git remote add origin <url>`
