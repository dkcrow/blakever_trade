## 任务背景
用户希望将 Notion 中的全部内容迁移到 IMA 知识库，保持原有的分类结构，并生成 .xmind 脑图整理碎片知识。

## 执行过程
1. 测试 IMA 连接：笔记和知识库模块均连接成功（code: 0）
2. 排查 Notion 权限：Integration 需手动在每个顶层页面添加 Connection 授权
3. 获取 Notion 页面列表：通过 search API + 手动补全 ID 获取到7个顶层页面
4. 递归获取子页面：遍历每个顶层页面的子页面链接，收集42个不完整 ID
5. 补全子页面完整 ID：从旧数据中查找并拼接为32位 UUID
6. 批量抓取内容：Python 脚本并发获取全部49个页面的 Markdown 内容并保存到 `notion_export/` 目录
7. 尝试上传 IMA：知识库 API `search_knowledge_base` 和 `get_addable_knowledge_base_list` 均返回空列表，上传受阻

## 关键结果
- ✅ 抓取成功：49个页面（7顶层+42子页），约1MB，56个markdown文件
- ✅ 文件保存位置：`C:\Users\blakehao\.qclaw\workspace
otion_export\`
- ✅ 生成了迁移状态报告：`notion_to_ima_migration_status.md`
- ❌ IMA 上传失败：知识库 API 返回空列表，权限/会话问题
- 📂 分类结构：职场17个、学习16个、运动4个、英语3个、财经2个、复盘规划1个、TODO1个

## 结论建议
Notion 内容已全部抓取完毕，但 IMA 知识库上传卡在 API 返回空列表。**建议用户**：①确认 IMA 账号是否有知识库写入权限；②尝试在 …