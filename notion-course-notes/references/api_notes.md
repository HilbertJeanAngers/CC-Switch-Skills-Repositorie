# Notion API 实战要点（本技能踩过的坑）

## 认证
- 用个人访问令牌（PAT，`ntn_` 开头）。PAT 继承本人权限，**能看所有自己可见的页面，无需逐页授权**。
  （若是 internal integration 的 token 才需要在 Access 标签分享页面——本技能默认 PAT。）
- 令牌从环境变量 `NOTION_TOKEN` 读，禁止写进脚本或落盘。
- 请求头必须带 `Notion-Version: 2022-06-28` 和 `Content-Type: application/json`。

## 关键接口
- 搜索页面：`POST /v1/search`，body 可带 `page_size`、`sort`。
- 读子块：`GET /v1/blocks/{id}/children?page_size=100&start_cursor=xxx`（`has_more` 时翻页）。
- 插入块：`PATCH /v1/blocks/{parent_id}/children`，body = `{"children":[...], "after":"<块id>"}`。
  - **`after` 必须放 body 里，不能放 URL query**——放 query 会 400 `query.after should be not present`。
  - `after` 填"目标位置前一个块的 id"，新块就插到它后面（即目标图前面）。
- 归档/恢复：`PATCH /v1/pages/{id}`，body = `{"archived": true/false}`。归档不删内容，可恢复。
- 图片 URL：`block.image.file.url`（上传图，临时签名）或 `block.image.external.url`（外链）。

## 课程笔记的结构规律
- 用户写笔记的习惯：一个**文字块（段落/callout/标题）当小标题**，下面挂若干张截图。
- 图片常挂在 heading 的 `has_children` 子块里，不是顶层——遍历时要递归进子块。
- "裸图"= 前面没有任何文字块的图片 = 需要补注释的目标。
- 有些块类型 API 读出来是 `unsupported`（特殊嵌入/看板），不要动，保持原样。

## 看图识别流程
1. `analyze_page.py` 找出裸图编号。
2. `prepare_images.py` 下载图片 → 生成 `sheet_*.jpg` 拼版（24张/页，带编号）。
3. 用看图工具看拼版；字太小就看 `zoom_*.png` 单张放大。
4. 逐张记住编号对应的知识点，再用 `insert_caption.py` 逐条插入。

## 折叠块 / 排版（用户偏好：可折叠标题）
- 用户要的"折叠"是**可折叠标题**（带小三角、保持标题字号层级），不是正文大小的普通 `toggle` block。
- 做法：heading_1/2/3 块带 `"is_toggleable": true`，内容放进同级 `children`（创建时一次性带）。用户偏好：章节用 heading_2、整篇总折叠用 heading_1。
- 迁移/重建整页到折叠标题内时：
  - **表格 table 必须在创建时一次性带 `children`(=table_row 数组) + `table_width`**，不能先建 table 再追加行，否则 400 `table.children should be defined`。table_row 用 `{"cells": [[rich_text], ...]}`。
  - 其他块可先建再递归追加子块；heading 的 `is_toggleable` 要在新建时就带上，后加会丢。
  - rich_text 重建只留 `type/text/link`（去掉 plain_text/annotations 等只读字段）。
  - 块多时批量 PATCH + sleep 会超时（SIGTERM）；若超时先重查页面状态，往往迁移已完成，别盲目重跑导致重复。

## 安全
- 改动前先 `backup_page.py` 留底。
- 临时脚本、下载的图片用完即删，避免明文令牌和垃圾落盘。
