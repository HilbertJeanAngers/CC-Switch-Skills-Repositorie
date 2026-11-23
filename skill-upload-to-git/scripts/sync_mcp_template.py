#!/usr/bin/env python3
"""MCP 配置模板双向同步：CC Switch 数据库 <-> 脱敏模板。

设计目标（用户约定）：
  - git 仓库里的模板是「真相」，密钥一律用 ${VAR} 占位符，绝不进版本控制。
  - CC Switch 退化为「切换器」：它仍保存各 agent 的启用开关，但配置内容以模板为准。

两个方向：
  export  DB  -> 模板   解析 server_config，把密钥/机器路径换成占位符后写出
  apply   模板 -> DB    读本机环境变量填回占位符，写回 DB（开关状态一并写回）

密钥来源优先级（apply 时）：环境变量 > 本机 DB 现有值 > 报错。
这样本机执行 apply 不会丢密钥；新机执行前只需填一次环境变量。
"""
import argparse
import copy
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = " ~/.cc-switch/cc-switch.db".strip()
AGENTS = [
    "claude", "codex", "gemini", "grokbuild", "opencode", "hermes", "mcode",
    "pi", "agy", "kimi", "omp", "dsh", "copilot", "workbuddy",
]

# 由 agent 自己生成、换机自动重建的 MCP，默认不纳入模板管理
MANAGED_BY_AGENT = {"node_repl"}

# 需要用户在本机提供的变量（不存值，只存说明）
ENV_DOC = {
    "CONTEXT7_API_KEY": "Context7 API key（ctx7sk-...），从 context7.com/dashboard 获取",
    "NOTION_TOKEN": "Notion integration token，本机通过用户环境变量提供（不写进 mcp.json）",
    "MYSQL_WTTG_HOST": "mysql-wttg / mcpServers-mysql 的数据库主机",
    "MYSQL_WTTG_PORT": "mysql-wttg / mcpServers-mysql 的端口",
    "MYSQL_WTTG_USER": "mysql-wttg / mcpServers-mysql 的用户",
    "MYSQL_WTTG_PASSWORD": "mysql-wttg / mcpServers-mysql 的密码",
    "MYSQL_WTTG_DATABASE": "mysql-wttg / mcpServers-mysql 的库名",
    "MYSQL_HDGT_HOST": "mysql-hdgt 的数据库主机",
    "MYSQL_HDGT_PORT": "mysql-hdgt 的端口",
    "MYSQL_HDGT_USER": "mysql-hdgt 的用户",
    "MYSQL_HDGT_PASSWORD": "mysql-hdgt 的密码",
    "MYSQL_HDGT_DATABASE": "mysql-hdgt 的库名",
    "MYSQL_ZHGT_HOST": "mysql-zhgt 的数据库主机",
    "MYSQL_ZHGT_PORT": "mysql-zhgt 的端口",
    "MYSQL_ZHGT_USER": "mysql-zhgt 的用户",
    "MYSQL_ZHGT_PASSWORD": "mysql-zhgt 的密码",
    "MYSQL_ZHGT_DATABASE": "mysql-zhgt 的库名",
    "USERPROFILE": "Windows 用户目录，通常系统已提供；apply 时自动取 Path.home()",
}

PLACEHOLDER = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")
BEARER = re.compile(r"(Bearer\s+)([A-Za-z0-9._\-]{8,})", re.I)
USERPATH_WIN = re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/]+", re.I)


def _scrub_str(s, var_hint=None):
    """把字符串里的密钥/机器路径换成占位符。"""
    if not isinstance(s, str):
        return s
    if PLACEHOLDER.search(s):          # 已经是占位符，原样保留
        return s

    def bearer_sub(m):
        token = m.group(2)
        name = "CONTEXT7_API_KEY" if "ctx7" in token.lower() else "MCP_API_KEY"
        return m.group(1) + "${" + name + "}"

    s = BEARER.sub(bearer_sub, s)
    # C:/Users/123456/... 或 C:\Users\123456\... -> ${USERPROFILE}/...
    s = USERPATH_WIN.sub("${USERPROFILE}", s)
    return s


def scrub(obj):
    """递归脱敏配置树。"""
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scrub(v) for v in obj]
    return _scrub_str(obj)


def load_db(db_path):
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    return con


def read_rows(con):
    rows = {}
    for r in con.execute("select id, name, server_config, description from mcp_servers"):
        d = dict(r)
        try:
            cfg = json.loads(d["server_config"])
        except Exception:
            cfg = {}
        on = {}
        for a in AGENTS:
            try:
                on[a] = bool(con.execute(
                    f"select enabled_{a} from mcp_servers where id=?", (d["id"],)
                ).fetchone()[0])
            except Exception:
                on[a] = False
        rows[d["id"]] = {
            "name": d["name"],
            "config": cfg,
            "enabled": on,
            "description": d["description"],
            "managed_by": "agent" if d["id"] in MANAGED_BY_AGENT else "user",
        }
    return rows


def do_export(db_path, template_path):
    con = load_db(db_path)
    rows = read_rows(con)
    con.close()
    servers = {}
    for mid, item in rows.items():
        cfg = scrub(copy.deepcopy(item["config"]))
        servers[mid] = {
            "config": cfg,
            "enabled": item["enabled"],
            "description": item["description"],
            "managed_by": item["managed_by"],
        }
    doc = {
        "_meta": {
            "description": "MCP 配置真相模板。密钥一律为 ${VAR} 占位符，禁止填写真实值。",
            "sync": "python sync_mcp_template.py export|apply",
            "exported_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "cc_switch_role": "切换器：保留各 agent 启用开关；配置内容以本模板为准",
        },
        "required_env": ENV_DOC,
        "mcp_servers": servers,
    }
    template_path.parent.mkdir(parents=True, exist_ok=True)
    template_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(servers), template_path


def fill(obj, resolvers):
    """递归替换 ${VAR}；返回 (结果, 缺失变量集合)。"""
    missing = set()

    def one(s):
        def sub(m):
            key = m.group(1)
            if key in resolvers and resolvers[key] not in (None, ""):
                return str(resolvers[key])
            missing.add(key)
            return m.group(0)
        return PLACEHOLDER.sub(sub, s)

    def walk(x):
        if isinstance(x, dict):
            return {k: walk(v) for k, v in x.items()}
        if isinstance(x, list):
            return [walk(v) for v in x]
        if isinstance(x, str):
            return one(x)
        return x

    return walk(obj), missing


def do_apply(db_path, template_path, dry_run, only=None):
    doc = json.loads(template_path.read_text(encoding="utf-8"))
    con = load_db(db_path)
    existing = read_rows(con)

    home = str(Path.home()).replace("\\", "/")
    resolvers = {"USERPROFILE": home}
    for key in ENV_DOC:
        val = os.environ.get(key)
        if val:
            resolvers[key] = val
    # 本机已有值作为密钥后备：避免在本机 apply 时丢失已配置的 token
    for mid, item in existing.items():
        cfg_text = json.dumps(item["config"], ensure_ascii=False)
        for key in ("CONTEXT7_API_KEY", "MCP_API_KEY"):
            m = re.search(r"(Bearer\s+)(" + r"[A-Za-z0-9._\-]{8,}" + r")", cfg_text, re.I)
            if m and key not in resolvers:
                resolvers[key] = m.group(2)

    changed, skipped, missing_all = [], [], set()
    for mid, item in doc.get("mcp_servers", {}).items():
        if only and mid not in only:
            continue
        if item.get("managed_by") == "agent" and mid not in existing:
            skipped.append((mid, "agent 自管且本机不存在"))
            continue
        cfg, missing = fill(copy.deepcopy(item["config"]), resolvers)
        missing_all |= missing
        if missing:
            skipped.append((mid, "缺变量 " + ",".join(sorted(missing))))
            continue
        if mid not in existing:
            skipped.append((mid, "本机 DB 无此 MCP，需先在 CC Switch 添加"))
            continue
        if not dry_run:
            con.execute(
                "update mcp_servers set server_config=? where id=?",
                (json.dumps(cfg, ensure_ascii=False), mid),
            )
            for a in AGENTS:
                if a in item.get("enabled", {}):
                    con.execute(f"update mcp_servers set enabled_{a}=? where id=?",
                                (1 if item["enabled"][a] else 0, mid))
        changed.append(mid)
    if not dry_run:
        con.commit()
    con.close()
    print("dry-run" if dry_run else "applied")
    print("  changed:", ", ".join(changed) if changed else "(none)")
    for mid, why in skipped:
        print("  skipped:", mid, "-", why)
    if missing_all:
        print("  需要设置的环境变量:", ", ".join(sorted(missing_all)))
        return 2
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("direction", choices=["export", "apply"])
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--template", default=str(Path(__file__).resolve().parent.parent / "mcp.template.json"))
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--only", nargs="*", help="只处理指定 MCP id")
    args = p.parse_args()
    db = Path(os.path.expanduser(args.db))
    tpl = Path(os.path.expanduser(args.template))
    if not db.exists():
        print("数据库不存在:", db); return 1
    if args.direction == "export":
        n, out = do_export(db, tpl)
        print(f"exported {n} MCP -> {out}")
        return 0
    if not tpl.exists():
        print("模板不存在:", tpl); return 1
    return do_apply(db, tpl, args.dry_run, set(args.only or []))


if __name__ == "__main__":
    sys.exit(main())
