# 第三方来源与许可

发布包仅分发应用源码、公开来源下载清单、界面截图和下述选定规则文档。不捆绑Python解释器、第三方Python包二进制、OCR权重或用户导入材料。

## Shenlun Master

- 作者：coffe-d。
- 仓库：<https://github.com/coffe-d/Shenlun.skill>。
- 固定提交：`354341cdce1f357bb78c24f05a929a339cd7f4cf`。
- 原MIT许可：`vendor/shenlun-master/LICENSE`。
- 文件清单与SHA-256：`vendor/shenlun-master/manifest.json`。
- 适配说明：`vendor/shenlun-master/NOTICE.md`。

只包含作者整理的选定规则和方法文档，不含原始讲义、真题语料、可执行脚本或使用者错题。原作者关于教学材料及其他权利的说明保留于其README。规则作为参考，不把老师建议冒充官方评分标准。

## 安装时获取的依赖

| 依赖 | 作用 | 已安装版本的许可标识或说明 |
| --- | --- | --- |
| openpyxl | XLSX读取 | MIT |
| pypdf | PDF文字和结构 | BSD-3-Clause |
| python-docx | DOCX读取 | MIT |
| RapidOCR | 本地文字识别 | Apache-2.0；模型另见其包内MODEL_LICENSES.md |
| ONNX Runtime | OCR模型运行 | MIT |
| pypdfium2 / PDFium | PDF渲染 | BSD-3-Clause、Apache-2.0及其依赖许可，见包内LICENSES |
| Pillow | 图像读写与裁剪 | MIT-CMU及包内相关声明 |
| ReportLab | 测试生成合成PDF | BSD类许可，见包内LICENSE |

这些包及传递依赖由安装工具获取，适用各自随包许可。模型、字体或二进制的额外分发应保留对应声明。本项目使用系统字体，不分发字体文件。

## 国考真题来源索引

ERRRC/xingcezhenti，提交 `278984401124db40da5163a31275b8deb9c282f4`。仅分发公开路径/校验清单与本项目适配代码，不捆绑题面、答案、解析及图片，不声明这些内容受本项目MIT许可覆盖。下载与使用说明见 `banks/guokao/README.md`。
