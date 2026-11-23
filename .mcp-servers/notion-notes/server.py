"""Notion Notes MCP Server — Notion 笔记能力中枢（唯一数据出入口）。

【架构约定】本 MCP 是"大脑"：唯一持有 Notion 访问能力（令牌 / API / 块构造），
所有对 Notion 的读写都必须经由此处。notion-course-notes skill 是"手"：只承载
流程判断与场景话术，不自行实现任何 API 访问。两者职责不重叠。

任何支持 MCP 的 agent（Codex / Claude Code / Cursor / WorkBuddy 等）通过 stdio 调用。
令牌来源优先级：环境变量 NOTION_TOKEN > Windows 用户级注册表（HKCU\\Environment）。

启动方式（由 MCP 客户端拉起，勿手动运行）：
    python C:/Users/123456/.mcp-servers/notion-notes/server.py
"""
import os
import sys
import json
import copy
import urllib.request
import urllib.error
from PIL import Image, ImageDraw, ImageFont

try:
    from mcp.server.mcpserver import MCPServer
except ImportError:
    from mcp.server.fastmcp import FastMCP as MCPServer  # mcp 1.x 兼容

VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"
TMP = os.environ.get("TEMP", os.environ.get("TMP", "/tmp"))
IMG_DIR = os.path.join(TMP, "mcp_notion_imgs")

server = MCPServer(
    name="notion-notes",
    instructions=(
        "Notion 能力中枢（大脑）：所有 Notion 访问的唯一出入口，凭据与 API 细节都在此处，"
        "不要自行用 curl / 脚本直连 Notion API。\n"
        "工具：notion_search、notion_read_page、notion_analyze_images、notion_download_image、"
        "notion_insert_caption、notion_append_blocks、notion_backup_page、notion_archive_page、"
        "notion_restore_page、notion_get_style_guide、notion_delete_blocks、notion_update_block、"
        "notion_nest_blocks、notion_move_blocks。\n"
        "场景流程由 notion-course-notes skill（手）决定；本 MCP 只提供能力，不做流程判断。\n"
        "通用约定：改动前先 notion_backup_page；风格与折叠规则先 notion_get_style_guide。"
    ),
)


# ---------- 令牌 ----------
def get_token():
    t = os.environ.get("NOTION_TOKEN", "").strip()
    if t:
        return t
    if sys.platform == "win32":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment")
            val, _ = winreg.QueryValueEx(key, "NOTION_TOKEN")
            if val and val.strip():
                return val.strip()
        except Exception:
            pass
    raise RuntimeError("未找到 NOTION_TOKEN：请在 MCP 客户端 env 中传入，或设置用户级环境变量。")


# ---------- 底层 API ----------
def api(method, path, body=None, timeout=40):
    url = BASE + path
    headers = {
        "Authorization": "Bearer " + get_token(),
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return False, json.loads(raw)
        except Exception:
            return False, {"object": "error", "status": e.code, "message": raw[:300]}
    except Exception as e:
        return False, {"object": "error", "message": str(e)}


def children(block_id, page_size=100):
    out, cursor = [], None
    while True:
        path = f"/blocks/{block_id}/children?page_size={page_size}"
        if cursor:
            path += f"&start_cursor={cursor}"
        ok, data = api("GET", path)
        if not ok:
            raise RuntimeError(f"读取子块失败: {data}")
        out.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def rich_text(block):
    c = block.get(block.get("type", ""), {}) or {}
    if "rich_text" in c:
        return "".join(x.get("plain_text", "") for x in c["rich_text"])
    if isinstance(c.get("title"), list):
        return "".join(x.get("plain_text", "") for x in c["title"])
    if block.get("type") == "child_page":
        return c.get("title", "")
    return ""


def page_title(page):
    for key, val in (page.get("properties") or {}).items():
        if val.get("type") == "title" and isinstance(val.get("title"), list):
            return "".join(x.get("plain_text", "") for x in val["title"])
    if page.get("child_page"):
        return page["child_page"].get("title", "")
    return ""


def resolve_page(ref):
    """ref 为页面 ID（含 - 且够长）直接取；否则按标题模糊搜索，返回唯一匹配页。"""
    ref = (ref or "").strip()
    if "-" in ref and len(ref) > 30:
        ok, page = api("GET", f"/pages/{ref}")
        if ok:
            return True, page
        return False, page
    ok, data = api("POST", "/search", {
        "page_size": 100,
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
    })
    if not ok:
        return False, data
    hits = [p for p in data.get("results", []) if p.get("object") == "page"
            and ref.lower() in page_title(p).lower()]
    if not hits:
        return False, {"message": f"未找到标题含 '{ref}' 的页面"}
    if len(hits) > 1:
        return False, {"message": "多个匹配，请用页面 ID 或更精确的标题",
                       "matches": [{"id": p["id"], "title": page_title(p)} for p in hits[:10]]}
    return True, hits[0]


def make_block(spec):
    """把简化 spec 转成 Notion block。支持 text/heading_1/2/3/code/quote/bullet/number/callout/divider/toggle。
    heading/toggle 支持 toggleable=true 变成可折叠标题；spec.children 可递归塞进块内。
    """
    typ = spec.get("type", "paragraph")
    text = spec.get("text", "")
    toggle = bool(spec.get("toggleable", spec.get("collapsed", False)))

    def rt(t):
        return [{"type": "text", "text": {"content": t}}]

    block = None
    if typ in ("paragraph", "text"):
        block = {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rt(text)}}
    elif typ in ("h1", "heading_1"):
        block = {"object": "block", "type": "heading_1",
                 "heading_1": {"rich_text": rt(text), "is_toggleable": toggle}}
    elif typ in ("h2", "heading_2"):
        block = {"object": "block", "type": "heading_2",
                 "heading_2": {"rich_text": rt(text), "is_toggleable": toggle}}
    elif typ in ("h3", "heading_3"):
        block = {"object": "block", "type": "heading_3",
                 "heading_3": {"rich_text": rt(text), "is_toggleable": toggle}}
    elif typ == "code":
        block = {"object": "block", "type": "code",
                 "code": {"rich_text": rt(text), "language": spec.get("language", "plain text")}}
    elif typ in ("quote",):
        block = {"object": "block", "type": "quote", "quote": {"rich_text": rt(text)}}
    elif typ in ("bullet", "bulleted_list_item"):
        block = {"object": "block", "type": "bulleted_list_item",
                 "bulleted_list_item": {"rich_text": rt(text)}}
    elif typ in ("number", "numbered_list_item"):
        block = {"object": "block", "type": "numbered_list_item",
                 "numbered_list_item": {"rich_text": rt(text)}}
    elif typ == "callout":
        icon = spec.get("icon", "📌")
        block = {"object": "block", "type": "callout",
                 "callout": {"rich_text": rt(text), "icon": {"type": "emoji", "emoji": icon}}}
    elif typ == "divider":
        block = {"object": "block", "type": "divider", "divider": {}}
    elif typ == "toggle":
        block = {"object": "block", "type": "toggle", "toggle": {"rich_text": rt(text),
                                                                "is_toggleable": True}}
    else:
        raise ValueError(f"不支持的块类型: {typ}")
    if spec.get("children"):
        key_map = {"text": "paragraph", "bullet": "bulleted_list_item",
                   "number": "numbered_list_item", "h1": "heading_1",
                   "h2": "heading_2", "h3": "heading_3"}
        inner_key = key_map.get(typ, typ)
        block[inner_key]["children"] = [make_block(c) for c in spec["children"]]
    return block


def font(size, bold=False):
    try:
        name = "msyhbd.ttc" if bold else "msyh.ttc"
        return ImageFont.truetype("C:/Windows/Fonts/" + name, size)
    except Exception:
        return ImageFont.load_default()


# ================= MCP 工具 =================

@server.tool()
def notion_search(query: str = "", limit: int = 20) -> str:
    """搜索 Notion 中可访问的页面。query 为空则列出最近编辑的页面。
    返回 JSON：{ok, results:[{id,title,edited}]}。用于先定位目标页面。"""
    ok, data = api("POST", "/search", {
        "page_size": min(limit, 100),
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
    })
    if not ok:
        return json.dumps({"ok": False, "error": data}, ensure_ascii=False)
    results = []
    for p in data.get("results", [])[:limit]:
        if p.get("object") == "page":
            results.append({"id": p["id"], "title": page_title(p),
                            "edited": p.get("last_edited_time", "")})
    return json.dumps({"ok": True, "results": results, "has_more": data.get("has_more", False)},
                      ensure_ascii=False)


@server.tool()
def notion_read_page(page_ref: str, max_blocks: int = 200) -> str:
    """读取页面的块结构（含标题层级与文本），用于了解现有内容和组织方式。
    page_ref 可以是页面标题关键词或页面 ID。返回 JSON：{ok,page_id,title,blocks:[...]}。"""
    ok, page = resolve_page(page_ref)
    if not ok:
        return json.dumps({"ok": False, "error": page}, ensure_ascii=False)
    blocks = []
    def walk(bid, depth=0, counter=[0]):
        for b in children(bid):
            if counter[0] >= max_blocks:
                return
            counter[0] += 1
            t = rich_text(b)
            blocks.append({"depth": depth, "type": b["type"], "text": t[:300],
                           "id": b["id"], "has_children": bool(b.get("has_children")),
                           "toggleable": bool((b.get(b["type"]) or {}).get("is_toggleable"))})
            if b.get("has_children"):
                walk(b["id"], depth + 1, counter)
    walk(page["id"])
    return json.dumps({"ok": True, "page_id": page["id"], "title": page_title(page),
                       "block_count": len(blocks), "blocks": blocks}, ensure_ascii=False)


@server.tool()
def notion_analyze_images(page_ref: str) -> str:
    """分析页面里所有图片，找出"前面没有文字说明"的裸图（需要补注释的图）。
    这是给网课/图文笔记补注释的入口。返回 JSON：
    {ok,page_id,images:[{n,block_id,parent_id,section,label,bare,url}]}，n 是图片编号。
    裸图 bare=true 表示缺注释。拿到编号后可 notion_download_image 看图，再 notion_insert_caption 补文字。"""
    ok, page = resolve_page(page_ref)
    if not ok:
        return json.dumps({"ok": False, "error": page}, ensure_ascii=False)
    images = []
    section, pending_label = "", ""
    img_no = 0
    label_types = ("paragraph", "callout", "heading_1", "heading_2", "heading_3",
                   "bulleted_list_item", "numbered_list_item", "toggle")
    top = children(page["id"])
    for b in top:
        t = rich_text(b)
        if b["type"].startswith("heading"):
            section = t
            pending_label = ""
        elif b["type"] in label_types and t.strip() and not b.get("has_children"):
            pending_label = t.strip()
        if b.get("has_children"):
            subs = children(b["id"])
            if t.strip() and not b["type"].startswith("heading"):
                pending_label = t.strip()
            for s in subs:
                st = rich_text(s)
                if s["type"] in label_types and st.strip():
                    pending_label = st.strip()
                if s["type"] == "image":
                    img_no += 1
                    img = s.get("image", {})
                    url = (img.get("file") or {}).get("url") or (img.get("external") or {}).get("url")
                    images.append({"n": img_no, "block_id": s["id"], "parent_id": b["id"],
                                   "section": section, "label": pending_label,
                                   "bare": not bool(pending_label.strip()), "url": url})
    bare_count = sum(1 for im in images if im["bare"])
    return json.dumps({"ok": True, "page_id": page["id"], "title": page_title(page),
                       "image_count": len(images), "bare_count": bare_count, "images": images},
                      ensure_ascii=False)


@server.tool()
def notion_download_image(url: str, name: str = "") -> str:
    """下载一张图片（通常是 notion_analyze_images 返回的 url）到本地临时目录，
    返回本地绝对路径，供 agent 的看图工具查看以识别图中知识点。
    注意：Notion 图片 URL 带签名会过期，需要时重新 analyze 获取新 url。"""
    if not url:
        return json.dumps({"ok": False, "error": "url 为空"}, ensure_ascii=False)
    try:
        os.makedirs(IMG_DIR, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=40) as r:
            buf = r.read()
        safe = "".join(c for c in (name or "img") if c.isalnum() or c in "_-")[:40]
        path = os.path.join(IMG_DIR, safe + ".png")
        with open(path, "wb") as f:
            f.write(buf)
        # 生成放大版，便于小字识别
        im = Image.open(path).convert("RGB")
        w, h = im.size
        if w < 1400:
            scale = 1400 / w
            im.resize((1400, int(h * scale))).save(os.path.join(IMG_DIR, safe + "_large.png"))
        return json.dumps({"ok": True, "path": path.replace("\\", "/"),
                           "large_path": os.path.join(IMG_DIR, safe + "_large.png").replace("\\", "/"),
                           "size": [w, h]}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)


@server.tool()
def notion_insert_caption(page_ref: str, image_block_id: str, text: str,
                          block_type: str = "paragraph") -> str:
    """在指定图片"前面"插入一行注释文字。image_block_id 来自 notion_analyze_images。
    block_type 可选：paragraph / h2 / h3 / callout。标题只写知识点名，不要加"（点击展开）"之类废话。
    插入前会检查前一块是否已是相同文字，避免重复。返回 {ok, inserted, block_id}。"""
    ok, page = resolve_page(page_ref)
    if not ok:
        return json.dumps({"ok": False, "error": page}, ensure_ascii=False)
    page_id = page["id"]
    parent_id, idx, kids = None, -1, None
    for b in children(page_id):
        if b.get("has_children"):
            subs = children(b["id"])
            hit = next((i for i, s in enumerate(subs) if s["id"] == image_block_id), -1)
            if hit >= 0:
                parent_id, kids, idx = b["id"], subs, hit
                break
    if parent_id is None:
        # 图片可能直接挂在页面顶层
        top = children(page_id)
        hit = next((i for i, s in enumerate(top) if s["id"] == image_block_id), -1)
        if hit >= 0:
            parent_id, kids, idx = page_id, top, hit
    if parent_id is None:
        return json.dumps({"ok": False, "error": "未定位到图片所在父块"}, ensure_ascii=False)
    if idx > 0 and rich_text(kids[idx - 1]).strip() == text.strip():
        return json.dumps({"ok": True, "inserted": False, "reason": "前一块已是相同注释"},
                          ensure_ascii=False)
    block = make_block({"type": block_type, "text": text})
    if idx > 0:
        ok2, data = api("PATCH", f"/blocks/{parent_id}/children",
                        {"children": [block], "after": kids[idx - 1]["id"]})
    else:
        ok2, data = api("PATCH", f"/blocks/{parent_id}/children", {"children": [block]})
    if ok2:
        new_id = (data.get("results") or [{}])[0].get("id")
        return json.dumps({"ok": True, "inserted": True, "block_id": new_id, "text": text},
                          ensure_ascii=False)
    return json.dumps({"ok": False, "error": data}, ensure_ascii=False)


@server.tool()
def notion_append_blocks(page_ref: str, blocks: str) -> str:
    """向页面末尾追加任意块（通用写入能力：知识库重建、加章节、加表格前的段落等）。
    blocks 是 JSON 数组字符串，每项形如 {"type":"h1","text":"一、简介","toggleable":true}。
    支持类型：text/paragraph、h1/h2/h3、code、quote、bullet、number、callout、divider、toggle。
    heading 设 toggleable=true 即为可折叠标题（一级标题建议折叠）。
    一次最多 100 个块（Notion API 限制）。返回 {ok,added}。"""
    try:
        specs = json.loads(blocks) if isinstance(blocks, str) else blocks
    except Exception as e:
        return json.dumps({"ok": False, "error": f"blocks 不是合法 JSON: {e}"}, ensure_ascii=False)
    if not isinstance(specs, list) or len(specs) > 100:
        return json.dumps({"ok": False, "error": "blocks 需为数组且不超过 100 项"}, ensure_ascii=False)
    ok, page = resolve_page(page_ref)
    if not ok:
        return json.dumps({"ok": False, "error": page}, ensure_ascii=False)
    try:
        payload = [make_block(s) for s in specs]
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    ok2, data = api("PATCH", f"/blocks/{page['id']}/children", {"children": payload})
    if ok2:
        return json.dumps({"ok": True, "added": len(payload), "page_id": page["id"]},
                          ensure_ascii=False)
    return json.dumps({"ok": False, "error": data}, ensure_ascii=False)


@server.tool()
def notion_backup_page(page_ref: str, output_path: str = "") -> str:
    """改动前备份页面完整内容到本地 JSON（可恢复）。page_ref 为标题或 ID。
    output_path 省略则自动存到临时目录。返回 {ok,path,block_count}。"""
    ok, page = resolve_page(page_ref)
    if not ok:
        return json.dumps({"ok": False, "error": page}, ensure_ascii=False)
    pid = page["id"]
    okp, pdata = api("GET", f"/pages/{pid}")
    if not okp:
        return json.dumps({"ok": False, "error": pdata}, ensure_ascii=False)
    snap = {"page_id": pid, "page": pdata, "blocks": {}}
    def walk(bid):
        bs = children(bid)
        snap["blocks"][bid] = bs
        for b in bs:
            if b.get("has_children"):
                walk(b["id"])
    try:
        walk(pid)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"遍历失败: {e}"}, ensure_ascii=False)
    path = output_path or os.path.join(TMP, f"notion_backup_{pid[:8]}.json")
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snap, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return json.dumps({"ok": False, "error": f"写文件失败: {e}"}, ensure_ascii=False)
    n = sum(len(v) for v in snap["blocks"].values())
    return json.dumps({"ok": True, "path": path.replace("\\", "/"), "block_count": n},
                      ensure_ascii=False)


@server.tool()
def notion_get_style_guide() -> str:
    """返回注释/布局的权威风格规则（本 MCP 目录下的 STYLE.md，唯一来源）。
    给图片补注释或整理笔记前先调用，确保风格一致（如一级标题必须折叠、标题不写废话后缀等）。
    改风格：直接编辑返回的 source 所指文件，一次修改全局生效。"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), "STYLE.md")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.dumps({"ok": True, "source": p.replace("\\", "/"), "content": f.read()},
                              ensure_ascii=False)
    return json.dumps({"ok": False, "error": "未找到 STYLE.md：" + p.replace("\\", "/"),
                       "hint": "默认风格：普通段落注释插在图前；一级标题用可折叠；标题只写知识点名。"},
                      ensure_ascii=False)


@server.tool()
def notion_archive_page(page_ids: str, remember: bool = True) -> str:
    """把页面移入 Notion 回收站（archived=true，不永久删除）。page_ids 为逗号分隔的 ID。
    remember=true 时把 ID 记入 %TEMP%/notion_archived_ids.json，供 notion_restore_page 批量撤销。
    改动前若只是想留底，优先用 notion_backup_page；归档适合"暂时移出视线"。"""
    ids = [x.strip() for x in (page_ids or "").split(",") if x.strip()]
    if not ids:
        return json.dumps({"ok": False, "error": "未提供页面 ID"}, ensure_ascii=False)
    archived, failed, done = [], [], []
    for pid in ids:
        ok, data = api("PATCH", f"/pages/{pid}", {"archived": True})
        if ok and data.get("archived") is True:
            archived.append(pid)
        else:
            failed.append({"id": pid, "error": data.get("message", str(data))})
    if remember and archived:
        log = os.path.join(TMP, "notion_archived_ids.json")
        try:
            old = []
            if os.path.exists(log):
                with open(log, encoding="utf-8") as f:
                    old = json.load(f)
            with open(log, "w", encoding="utf-8") as f:
                json.dump(list(dict.fromkeys(old + archived)), f, ensure_ascii=False)
            done.append(log.replace("\\", "/"))
        except Exception as e:
            failed.append({"id": "(记录文件)", "error": str(e)})
    return json.dumps({"ok": len(failed) == 0, "archived": archived,
                       "failed": failed, "log": done}, ensure_ascii=False)


@server.tool()
def notion_restore_page(page_ids: str, from_archive_log: bool = False) -> str:
    """恢复被归档（移入回收站）的 Notion 页面：把 archived 置回 false。
    page_ids 是逗号分隔的页面 ID；from_archive_log=true 时从 %TEMP%/notion_archived_ids.json
    读取之前归档过的 ID 批量恢复。这是"撤销归档"，不是内容回滚；内容回滚请用备份 JSON。
    返回 {ok, restored:[...], failed:[...]}。"""
    ids = []
    if from_archive_log:
        log = os.path.join(TMP, "notion_archived_ids.json")
        if not os.path.exists(log):
            return json.dumps({"ok": False, "error": "没有归档记录：" + log.replace("\\", "/")},
                              ensure_ascii=False)
        try:
            with open(log, encoding="utf-8") as f:
                ids = json.load(f)
        except Exception as e:
            return json.dumps({"ok": False, "error": f"读取归档记录失败: {e}"}, ensure_ascii=False)
    else:
        ids = [x.strip() for x in (page_ids or "").split(",") if x.strip()]
    if not ids:
        return json.dumps({"ok": False, "error": "未提供页面 ID"}, ensure_ascii=False)
    restored, failed = [], []
    for pid in ids:
        ok, data = api("PATCH", f"/pages/{pid}", {"archived": False})
        if ok and data.get("archived") is False:
            restored.append(pid)
        else:
            failed.append({"id": pid, "error": data.get("message", str(data))})
    return json.dumps({"ok": len(failed) == 0, "restored": restored, "failed": failed},
                      ensure_ascii=False)


# ---------- 原地编辑：块复制 / 删除 / 更新 / 折叠嵌套 ----------
def _clean_rt(vals):
    """把 API 返回的 rich_text 精简成可安全重建的形式。"""
    out = []
    for v in vals or []:
        if v.get("type") == "text":
            out.append({"type": "text", "text": {"content": v.get("text", {}).get("content", "")}})
        elif v.get("type") == "equation":
            out.append({"type": "equation",
                        "equation": {"expression": v.get("equation", {}).get("expression", "")}})
    return out


def _strip_nulls(obj):
    """递归剥掉 None 值——Notion 创建接口对 null 字段会报 validation_error。"""
    if isinstance(obj, dict):
        return {k: _strip_nulls(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [_strip_nulls(x) for x in obj]
    return obj


def block_to_payload(b, with_children=True):
    """把 GET /blocks/{id} 的返回块转成可直接 append 的 payload（剥掉只读字段，保留正文与子块）。"""
    t = b.get("type")
    if not t:
        raise ValueError("块缺少 type 字段")
    body = copy.deepcopy(b.get(t) or {})
    body = _strip_nulls(body)
    if "rich_text" in body:
        body["rich_text"] = _clean_rt(body["rich_text"])
    if "caption" in body and isinstance(body["caption"], list):
        body["caption"] = _clean_rt(body["caption"])
    if t == "table":
        body = {"table_width": body.get("table_width", 1),
                "has_column_header": bool(body.get("has_column_header")),
                "has_row_header": bool(body.get("has_row_header"))}
    elif t == "table_row":
        body = {"cells": [_clean_rt(c) for c in body.get("cells", [])]}
    payload = {"object": "block", "type": t, t: body}
    if with_children and b.get("has_children"):
        kids = children(b["id"])
        payload[t]["children"] = [block_to_payload(k, with_children=(k["type"] != "table_row"))
                                  for k in kids]
    return payload


def get_block(block_id):
    ok, data = api("GET", f"/blocks/{block_id}")
    if not ok:
        raise RuntimeError(f"读取块失败 {block_id}: {data}")
    return data.get("block") or data


def _log_deleted(ids, logged):
    path = os.path.join(TMP, "notion_deleted_block_ids.json")
    old = []
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = []
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(dict.fromkeys(old + ids)), f, ensure_ascii=False)
    logged.append(path.replace("\\", "/"))


@server.tool()
def notion_delete_blocks(block_ids: str, dry_run: bool = False) -> str:
    """原地删除（归档）指定块，同步记录到 %TEMP%/notion_deleted_block_ids.json 供批量恢复。
    block_ids 为逗号分隔的块 ID。dry_run=true 只校验不删除。返回 {ok,deleted,failed,log}。
    这解决"旧块只能追加不能删"的问题。"""
    ids = [x.strip() for x in (block_ids or "").split(",") if x.strip()]
    if not ids:
        return json.dumps({"ok": False, "error": "未提供块 ID"}, ensure_ascii=False)
    deleted, failed, logged = [], [], []
    for bid in ids:
        if dry_run:
            ok, data = True, {"dry_run": True}
        else:
            ok, data = api("PATCH", f"/blocks/{bid}", {"archived": True})
        if ok:
            deleted.append(bid)
        else:
            failed.append({"id": bid, "error": data.get("message", str(data))})
    if deleted and not dry_run:
        _log_deleted(deleted, logged)
    return json.dumps({"ok": len(failed) == 0, "deleted": deleted,
                       "failed": failed, "log": logged, "dry_run": dry_run},
                      ensure_ascii=False)


@server.tool()
def notion_restore_blocks(block_ids: str = "", from_log: bool = False) -> str:
    """恢复被 notion_delete_blocks 归档的块。from_log=true 从记录文件全量恢复；
    或传逗号分隔 block_ids。返回 {ok,restored,failed}。"""
    ids = []
    if from_log:
        path = os.path.join(TMP, "notion_deleted_block_ids.json")
        if os.path.exists(path):
            try:
                with open(path, encoding="utf-8") as f:
                    ids = json.load(f)
            except Exception as e:
                return json.dumps({"ok": False, "error": f"读记录失败: {e}"}, ensure_ascii=False)
        else:
            return json.dumps({"ok": False, "error": "没有删除记录文件"}, ensure_ascii=False)
    else:
        ids = [x.strip() for x in (block_ids or "").split(",") if x.strip()]
    restored, failed = [], []
    for bid in ids:
        ok, data = api("PATCH", f"/blocks/{bid}", {"archived": False})
        if ok and data.get("archived") is False:
            restored.append(bid)
        else:
            failed.append({"id": bid, "error": data.get("message", str(data))})
    if from_log and restored:
        try:
            with open(os.path.join(TMP, "notion_deleted_block_ids.json"), "w", encoding="utf-8") as f:
                json.dump([i for i in ids if i not in restored], f, ensure_ascii=False)
        except Exception:
            pass
    return json.dumps({"ok": len(failed) == 0, "restored": restored, "failed": failed},
                      ensure_ascii=False)


@server.tool()
def notion_update_block(block_id: str, patch: str, dry_run: bool = False) -> str:
    """原地更新一个块。patch 是 JSON 对象字符串，形如
    {"heading_1":{"is_toggleable":true}} 或 {"paragraph":{"rich_text":[{"type":"text","text":{"content":"新文字"}}]}}。
    可用于把已有标题改成可折叠、改文字、改 to_do 勾选等。返回 {ok,block_id,patched}。"""
    try:
        p = json.loads(patch) if isinstance(patch, str) else patch
    except Exception as e:
        return json.dumps({"ok": False, "error": f"patch 不是合法 JSON: {e}"}, ensure_ascii=False)
    if not isinstance(p, dict):
        return json.dumps({"ok": False, "error": "patch 必须是 JSON 对象"}, ensure_ascii=False)
    if dry_run:
        return json.dumps({"ok": True, "dry_run": True, "block_id": block_id, "patch": p},
                          ensure_ascii=False)
    ok, data = api("PATCH", f"/blocks/{block_id}", p)
    if ok:
        return json.dumps({"ok": True, "block_id": block_id, "patched": list(p.keys()),
                           "block": {"id": data.get("id"), "type": data.get("type")}},
                          ensure_ascii=False)
    return json.dumps({"ok": False, "error": data, "block_id": block_id}, ensure_ascii=False)


@server.tool()
def notion_nest_blocks(heading_block_id: str, block_ids: str, dry_run: bool = False) -> str:
    """解决"折叠标题塞不进子块"：把指定的同级块**复制进**可折叠标题的 children，
    校验复制成功后才删除原块（先复制后删，永不先删）。适用于 heading_1/2/3 与 toggle 块。
    heading 若未折叠会自动设为 is_toggleable=true。返回 {ok,heading_id,nested,deleted,failed}。"""
    ids = [x.strip() for x in (block_ids or "").split(",") if x.strip()]
    if not ids:
        return json.dumps({"ok": False, "error": "未提供要嵌套的块 ID"}, ensure_ascii=False)
    try:
        h = get_block(heading_block_id)
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    ht = h.get("type", "")
    if not ht.startswith("heading") and ht != "toggle":
        return json.dumps({"ok": False, "error": f"目标块不是标题/折叠块: {ht}"}, ensure_ascii=False)
    if not (h.get(ht) or {}).get("is_toggleable"):
        if dry_run:
            pass
        else:
            # Notion 要求改 is_toggleable 时同时提交 rich_text，否则 400
            payload = copy.deepcopy(h.get(ht) or {})
            payload["is_toggleable"] = True
            okp, dp = api("PATCH", f"/blocks/{heading_block_id}", {ht: payload})
            if not okp:
                return json.dumps({"ok": False, "error": "设置折叠失败", "detail": dp},
                                  ensure_ascii=False)
    before = 0 if dry_run else len(children(heading_block_id))
    payloads = []
    errors = []
    for bid in ids:
        try:
            payloads.append(block_to_payload(get_block(bid)))
        except Exception as e:
            errors.append({"id": bid, "error": str(e)})
    if errors:
        return json.dumps({"ok": False, "error": "读取待嵌套块失败", "failed": errors},
                          ensure_ascii=False)
    nested, failed = [], []
    if not dry_run:
        for i in range(0, len(payloads), 100):
            ok, data = api("PATCH", f"/blocks/{heading_block_id}/children",
                           {"children": payloads[i:i + 100]})
            if ok:
                nested.extend([r.get("id") for r in data.get("results", [])])
            else:
                failed.append({"batch": i // 100, "error": data.get("message", str(data))})
        after = 0 if dry_run else len(children(heading_block_id))
        if failed or after < before + len(payloads):
            # 回滚：删掉本次已复制进去的块，避免留下重复；原块始终未删
            if nested:
                api("POST", "/batch", {"requests": [
                    {"method": "DELETE", "path": f"/blocks/{nid}"} for nid in nested]})
            return json.dumps({"ok": False, "error": "复制进折叠块失败，已回滚副本，原块未删除",
                               "before": before, "after": after, "failed": failed,
                               "rolled_back": len(nested)}, ensure_ascii=False)
    okd = {"ok": True, "deleted": [], "failed": [], "log": []}
    if not dry_run:
        okd = json.loads(notion_delete_blocks(",".join(ids)))
    return json.dumps({"ok": okd["ok"] and not failed, "heading_id": heading_block_id,
                       "nested": nested or [f"dry:{i}" for i in ids],
                       "deleted": okd["deleted"], "failed": okd["failed"] + failed,
                       "log": okd.get("log", []), "dry_run": dry_run}, ensure_ascii=False)


@server.tool()
def notion_move_blocks(block_ids: str, after_block_id: str, dry_run: bool = False) -> str:
    """原地重排：把 block_ids 按顺序移动到 after_block_id 之后（同一父块内）。
    实现为"复制到目标位置 → 校验 → 删原块"，不先删。after_block_id 为空表示移到末尾。
    返回 {ok,moved,new_ids,deleted,failed}。"""
    ids = [x.strip() for x in (block_ids or "").split(",") if x.strip()]
    if not ids:
        return json.dumps({"ok": False, "error": "未提供块 ID"}, ensure_ascii=False)
    try:
        first = get_block(ids[0])
    except Exception as e:
        return json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)
    parent = first.get("parent") or {}
    parent_id = parent.get("page_id") or parent.get("block_id")
    if not parent_id:
        return json.dumps({"ok": False, "error": "无法确定父块"}, ensure_ascii=False)
    payloads, errors = [], []
    for bid in ids:
        try:
            payloads.append(block_to_payload(get_block(bid)))
        except Exception as e:
            errors.append({"id": bid, "error": str(e)})
    if errors:
        return json.dumps({"ok": False, "error": "读取块失败", "failed": errors}, ensure_ascii=False)
    new_ids, failed = [], []
    if not dry_run:
        body = {"children": payloads}
        if after_block_id:
            body["after"] = after_block_id
        ok, data = api("PATCH", f"/blocks/{parent_id}/children", body)
        if ok:
            new_ids = [r.get("id") for r in data.get("results", [])]
        else:
            failed.append({"error": data.get("message", str(data))})
        if failed or len(new_ids) < len(payloads):
            return json.dumps({"ok": False, "error": "复制重排失败，原块未删除",
                               "failed": failed}, ensure_ascii=False)
    okd = {"ok": True, "deleted": [], "failed": [], "log": []}
    if not dry_run:
        okd = json.loads(notion_delete_blocks(",".join(ids)))
    return json.dumps({"ok": okd["ok"] and not failed, "moved": ids, "new_ids": new_ids,
                       "deleted": okd["deleted"], "failed": okd["failed"] + failed,
                       "log": okd.get("log", []), "dry_run": dry_run}, ensure_ascii=False)


if __name__ == "__main__":
    server.run(transport="stdio")
