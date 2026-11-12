# 架构与开发入口

后端为Python标准库HTTP服务与SQLite，前端为原生HTML/CSS/JavaScript。状态保存在项目本地，文档、图像及OCR依赖按需加载。

| 文件 | 职责 |
| --- | --- |
| app.py | HTTP、存储、题库、练习、成绩及模型配置与请求 |
| file_imports.py / document_io.py | 分片批量上传、队列与文档解析 |
| book_import.py / library_rebuild.py | 跨页题块、选项、答案和材料重建 |
| local_ocr.py / file_pages.py | 本地OCR、PDF渲染、缓存和页面资源 |
| page_assist.py / question_reading.py | 选页辅助、裁图与阅读展示 |
| knowledge_index.py / knowledge_reader.py | 资料索引、全文阅读与检索 |
| learning_analysis.py | 确认后的增量分析、指纹、保存与复用 |
| learning_coach.py | 思路记录、能力假设、短训练和复测 |
| shenlun.py / shenlun_dimensions.py | 方法适配、引用校验、申论报告及维度证据 |
| calculation_training.py | 公式出题、容差、计时和独立计算记录 |
| web/ | 网页与界面资源 |
| national_bank.py / banks/guokao/ | 固定来源索引、受限题面解析、配图、题库归档与恢复 |
| tests/ | 临时库、合成资料与本地模拟接口 |
| vendor/shenlun-master/ | 固定版本规则、许可和清单 |
| scripts/build_release.py | 白名单打包、敏感模式检查及SHA-256清单 |

开发使用独立端口与数据目录：

```powershell
python app.py --port 8766 --data-dir work/qa-data
```

健康检查为`GET /api/health`。正式默认端口8765。

原始作答与成绩保留，AI报告和派生训练独立存储。综合分析通过指纹识别新增与修订，计划令牌校验范围，结果、覆盖游标和新任务在同一事务保存。

计算训练使用`calculation_sessions`，不造题写入原题库或推进综合分析覆盖。申论观察绑定来源、版本、原句和材料，同题去重，来源修订仅让相关依据失效。

开发应保持这些边界：不编造诊断，不覆盖历史成绩，不在预览时付费调用，不发送不可靠的整页多题图。
