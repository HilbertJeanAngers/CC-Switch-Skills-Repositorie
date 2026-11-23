---
name: skill-upload-to-git
description: 把 skill 库复刻/同步到目标文件夹，提交并推送到对应 git 仓库。用于用户说"同步 skill 到仓库""把 skill 上传 git""复刻 skill 库""更新 skill 仓库""skill上传git仓库"等场景。默认源为 CC Switch 的 skill 库，默认目标为 D:\My_Program\Ai Work_Space\My Skills。
---

# Skill 上传 Git 仓库

把源 skill 库复刻到目标文件夹，提交并推送到对应 git 仓库。核心是**先对比、再复刻、推送后查远端真实指针**，**同名 skill 用源（新版）逐文件覆盖目标的同名文件，目标独有的脚本/参考文档保留**。

## 默认路径

| 角色 | 路径 |
|---|---|
| 源（CC Switch skill 库） | `C:/Users/123456/.cc-switch/skills/` |
| 目标文件夹 | `D:/My_Program/Ai Work_Space/My Skills/` |
| 目标 git 仓库 | 读目标文件夹的 `git remote -v`（当前 `HilbertJeanAngers/CC-Switch-Skills-Repositorie`） |

用户可覆盖源/目标。CC Switch 登记的 skill 仓库列表在 `C:/Users/123456/.cc-switch/cc-switch.db` 的 `skill_repos` 表（含 owner/name/branch/host）。

## 流程

### 1. 摸清现状（只读）

- 列出源目录的 skill 文件夹、目标目录的 skill 文件夹
- 检查目标是否 git 仓库：`git -C <目标> remote -v`、`git -C <目标> status -sb`
- 检查本地 HEAD 与已记录的远端：`git -C <目标> rev-parse HEAD`、`git -C <目标> log origin/main --oneline -3`

### 2. 复刻/同步（先 dry-run）

```bash
python "C:/Users/123456/.workbuddy/skills/skill-upload-to-git/scripts/sync_skills.py" --source "<源>" --target "<目标>" --dry-run
```

脚本会列出三类差异：**目标缺失**（将复制）、**目标独有**（保留）、**同名但内容不同**（逐文件覆盖同名）。

**默认规则**（在目标基础上用新版改写）：同名但内容不同时，把源的文件**逐个覆盖到目标的同名文件**，而目标里独有的 `scripts/`、`references/` 等文件/目录**全部保留、不删除**。例如 `notion-course-notes` 会用源的新版 `SKILL.md` 覆盖目标的旧版，但目标自带的脚本和参考文档不受影响。这是默认行为，不需额外参数。确认 dry-run 结果无误后去掉 `--dry-run` 执行。

**仅当明确想保留目标旧版文件时**才加 `--keep-target`（旧行为：同名保留目标、不覆盖）。

### 3. 提交与推送

```bash
cd "<目标>"
git add -A
git status --short              # 确认改动符合预期，再提交
git commit -m "<描述本次改动的 message>"
git push origin <branch>        # branch 一般是 main
```

### 4. 验证（必做）

本地 `origin/main` 只是缓存引用，**不能只信它**。必须查远端服务器真实指针，与本地 HEAD 比对：

```bash
git ls-remote origin refs/heads/main
git rev-parse HEAD
```

两者哈希一致才算推送成功。

### 5. 报告

说清楚：同步了哪些 skill、提交了什么、远端指针是否一致。

## 幂等原则

若第 1 步发现源与目标一致，且 `ls-remote` 哈希与 HEAD 一致，说明早已同步完成——**直接报告现状，不要做无谓的 commit/push**。

## 注意

- 中文目录名在 git 里正常，不必改成英文
- 推送属于外部动作，若用户只说"复刻/同步"而没说"上传"，做到复刻即可，推送前确认
- 目标若还不是 git 仓库，先问用户要哪个远端仓库，再 `git init` + `git remote add origin <url>`
