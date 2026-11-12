# 安装、启动与迁移

## 环境

- Windows 10/11，Python 3.11或以上，推荐3.12。
- 解压到当前用户可写的目录，无需管理员权限，不建议放到Program Files。
- 首次安装依赖与默认国考真题需要联网。真题校验通过后可离线练习，识别使用本地OCR。
- 发布包不含预装依赖或权重，大文件解析还需要缓存空间。

## 首次使用

1. 解压全部文件，保留目录结构。
2. 双击“首次安装.cmd”，等待依赖安装、OCR检查与真题下载校验。
3. 双击“启动知序.cmd”，访问 <http://127.0.0.1:8765>。
4. 进入真题练习。已有题库不会自动替换，在“我的题库→国考真题库”确认后替换。模型配置自行填写。

只使用基础练习和计算训练时，安装Python后即可直接启动。PDF、Word、Excel及扫描页导入需要相应依赖。

```powershell
.\install-dependencies.ps1
.\service.ps1 -Action start
.\service.ps1 -Action status
.\service.ps1 -Action stop
```

目录可含中文和空格。默认端口8765，其他端口可手动指定：

```powershell
.\service.ps1 -Action start -Port 8767
# 手动访问 http://127.0.0.1:8767
.\service.ps1 -Action status -Port 8767
.\service.ps1 -Action stop -Port 8767
```

双击启动脚本默认打开8765。默认日志在`work/server.out.log`和`work/server.err.log`，其他端口使用端口后缀文件。

## 升级与迁移

1. 停止原服务，备份完整`data/`。
2. 新版解压到新目录，将备份的`data/`复制进去。
3. 重新安装依赖，不复制旧`.venv/`。
4. 确认旧服务停止后启动新版，核对题库与学习记录。
5. 跨Windows账号或电脑时重新填写API Key，原凭据不保证可以解密。

首次启动会创建所需数据表。JSON导出不含凭据及全部原始附件，当前没有完整JSON一键恢复入口；完整恢复使用文件夹备份。

## 常见问题

- 找不到Python：检查安装，重新打开终端，执行`py -3 --version`或`python --version`。
- OCR未就绪：重试首次安装，检查网络、安装输出及项目`.venv`。
- 服务无法启动：查看`work/`错误日志，检查端口、Python版本和目录写权限。
- 模型请求失败：检查服务地址、模型、余额和超时；图像分析需要视觉支持，不要将密钥贴到公开Issue。
- 扫描结果不全：核对原页和识别模式，只对相关失败页补识别。

开发测试安装`requirements-dev.txt`后运行`python -m unittest discover -s tests -q`。DPAPI测试需要当前Windows用户权限，OCR测试使用Windows中文字体。测试使用临时数据和本地模拟接口。
