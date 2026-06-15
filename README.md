# NJUST 一键自动评教

南京理工大学强智教务系统自动评教脚本，纯 `requests` API 调用，不依赖浏览器，命令行运行。

## 功能

- **一键评教** — 自动保存 + ≥90 分自动提交
- **仅保存不提交** — 保存评分后停下，手动检查分数
- **强制覆盖重做** — 已提交的课程也能覆盖，救回低分
- **智能评分** — 随机一个指标打第二高分（良），其余最高分（优）
- **多老师课程** — 同一门课多个老师自动识别
- **零依赖外部文件** — 单文件夹带走就能跑

## 快速开始

```bash
pip install -r requirements.txt
python auto_evaluate.py
```

启动后选择模式：

```
  模式选择:
    [1] 一键评教（保存 + ≥90分自动提交）
    [2] 仅保存不提交
    [3] 强制覆盖重做（含已提交课程）
  请输入 [1/2/3]（默认1）:
```

然后输入学号密码即可。

## 文件结构

```
评教/
├── auto_evaluate.py    # 主入口
├── fetcher.py          # 核心逻辑（登录 + 评教 API）
├── captcha/            # 验证码识别（OpenCV 模板匹配）
├── capture_pj.py       # Playwright 抓包工具（接口分析用）
├── captured_pj_api.json # 抓包结果（分析用）
└── requirements.txt
```

## 依赖

```
requests>=2.28
beautifulsoup4>=4.12
opencv-python>=4.8
numpy>=1.24
```

## 原理

基于 QFNU-Auto-XSPJ 的强智教务解析方式，纯 API 交互：

1. 登录 → POST `Logon.do` + 验证码识别
2. 解析 `xspj_find.do` → 获取评价批次
3. 解析 `xspj_list.do` → 获取课程列表
4. 解析 `xspj_edit.do` → 获取评价表单结构
5. POST `xspj_save.do` → 保存/提交评分

## 协议

本项目仅供学习交流使用。使用本工具产生的任何后果由使用者自行承担。

---

> 反馈邮箱：3353538260@qq.com
