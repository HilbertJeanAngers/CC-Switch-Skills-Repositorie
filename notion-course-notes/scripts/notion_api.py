"""Notion API 公共模块。所有脚本复用它。
令牌从环境变量 NOTION_TOKEN 读取，禁止写入脚本或落盘。
"""
import os
import json
import urllib.request
import urllib.error

VERSION = "2022-06-28"
BASE = "https://api.notion.com/v1"


def get_token():
    token = os.environ.get("NOTION_TOKEN", "").strip()
    if not token:
        raise RuntimeError(
            "未找到 NOTION_TOKEN 环境变量。请先设置：\n"
            "  PowerShell: $env:NOTION_TOKEN='ntn_xxx'  （仅当前会话）\n"
            "  永久设置：setx NOTION_TOKEN 'ntn_xxx'  （重开终端生效）"
        )
    return token


def request(method, path, body=None):
    """发起 Notion API 请求，返回 (ok, data)。"""
    url = BASE + path
    headers = {
        "Authorization": "Bearer " + get_token(),
        "Notion-Version": VERSION,
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return False, json.loads(e.read().decode("utf-8"))
    except Exception as e:
        return False, {"object": "error", "message": str(e)}


def children(block_id, page_size=100):
    """取某 block 的全部子块（自动翻页）。"""
    out, cursor = [], None
    while True:
        path = f"/blocks/{block_id}/children?page_size={page_size}"
        if cursor:
            path += f"&start_cursor={cursor}"
        ok, data = request("GET", path)
        if not ok:
            raise RuntimeError(f"读取子块失败: {data}")
        out.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return out


def rich_text(block):
    """提取 block 的纯文本。"""
    c = block.get(block.get("type", ""), {}) or {}
    if "rich_text" in c:
        return "".join(x.get("plain_text", "") for x in c["rich_text"])
    if isinstance(c.get("title"), list):
        return "".join(x.get("plain_text", "") for x in c["title"])
    if block.get("type") == "child_page":
        return c.get("title", "")
    return ""


def image_url(block):
    """取图片 block 的下载 URL。"""
    if block.get("type") != "image":
        return None
    img = block.get("image", {})
    if img.get("type") == "external":
        return img.get("external", {}).get("url")
    return img.get("file", {}).get("url")


def find_page(title_contains):
    """按标题模糊搜索页面，返回匹配列表 [{id, title, edited}]。"""
    ok, data = request("POST", "/search", {
        "page_size": 100,
        "sort": {"direction": "descending", "timestamp": "last_edited_time"},
    })
    if not ok:
        raise RuntimeError(f"搜索失败: {data}")
    out = []
    for p in data.get("results", []):
        if p.get("object") != "page":
            continue
        t = ""
        for key, val in (p.get("properties") or {}).items():
            if val.get("type") == "title":
                t = "".join(x.get("plain_text", "") for x in val.get("title", []))
                break
        if not t and p.get("child_page"):
            t = p["child_page"].get("title", "")
        if title_contains.lower() in t.lower():
            out.append({"id": p["id"], "title": t, "edited": p.get("last_edited_time", "")})
    return out


def insert_after(parent_id, after_block_id, block_spec):
    """在 parent 的子块中 after_block_id 之后插入新块。
    注意：after 必须放在 body 里，不能放 URL query（放了会 400）。
    """
    body = {
        "children": [block_spec],
        "after": after_block_id,
    }
    return request("PATCH", f"/blocks/{parent_id}/children", body)


def paragraph_block(text):
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }


def heading3_block(text):
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {
            "rich_text": [{"type": "text", "text": {"content": text}}]
        },
    }
