# MCP 配置模板：真相在 git，CC Switch 只做切换器

## 要解决什么

CC Switch 的 `cc-switch.db` 记录了所有 MCP 的定义和各 agent 的启用开关，但它是二进制 SQLite，且里面**明文存着 API token**。直接复制 `.cc-switch` 迁移，等于把密钥一起搬走，而且配置改了没有 diff 可查。

这套模板把「配置内容」抽成 git 里的纯文本真相文件，密钥一律留空（占位符），CC Switch 退化成切换器——它仍负责各 agent 的开关和投影，但内容以模板为准。

## 文件

| 文件 | 作用 |
|---|---|
| `.mcp-servers/mcp.template.json` | 真相模板：7 个 MCP 的完整配置 + 启用开关，**所有密钥是 `${VAR}` 占位符** |
| `scripts/sync_mcp_template.py` | 双向同步：`export` 从数据库生成模板，`apply` 从模板回填数据库 |

## 日常用法（本机改了 MCP 之后）

```bash
python scripts/sync_mcp_template.py export
```

把数据库现状重新导出成模板（密钥自动脱敏）。检查 diff 后提交到 git。

## 换电脑时

1. `git clone` 这个仓库
2. 在本机设置环境变量（模板 `required_env` 段列出了全部）：
   - `CONTEXT7_API_KEY` — Context7 的 key
   - `MYSQL_*` — 各 MySQL 连接的主机/端口/用户/密码/库名
   - `NOTION_TOKEN` — Notion token（走用户环境变量，不写进配置）
   - `USERPROFILE` — 系统自带，一般不用管
3. 先装好 CC Switch 并让它生成一次数据库（里面有 MCP 表结构）
4. 回填：

```bash
python scripts/sync_mcp_template.py apply --db <新机>/.cc-switch/cc-switch.db --dry-run
python scripts/sync_mcp_template.py apply --db <新机>/.cc-switch/cc-switch.db
```

`apply` 做的是：读模板 → 用本机环境变量填占位符 → 写回数据库的 `server_config` 与启用开关。密钥来源优先级：**环境变量 > 本机数据库现有值**，所以在本机直接 `apply` 不会丢已配好的 token。

## 两个边界

- **由 agent 自管的 MCP 不纳入模板**：`node_repl` 由 Codex 自动生成，换机后 Codex 会重建，模板里标记 `managed_by: agent`，本机若不存在就跳过。
- **notion-notes 的代码仍单独备份**：模板只管启动命令（含 `${USERPROFILE}` 占位符），`server.py` 等代码在 `.mcp-servers/notion-notes/`，随仓库一起走。换机后需把代码放到 `${USERPROFILE}/.mcp-servers/notion-notes/`，或改模板里的路径指向仓库位置。

## 安全红线

- 模板里**永远不要**填真实 token / 密码。提交前用 `grep -i 'ctx7sk\|password.*[^$]\|Bearer [A-Za-z0-9]'` 扫一遍。
- `cc-switch.db` 含明文密钥，不进 git（仓库的 `.gitignore` 已忽略点开头目录里的数据库文件，实际数据库在用户目录，本来就不在仓库）。
