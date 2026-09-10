<div align="center">

# Right Code Image

**在 Codex、Claude Code 和 WorkBuddy 中使用 Right Code 生成和修改图片**

![Agents](https://img.shields.io/badge/agents-Codex%20%7C%20Claude%20Code%20%7C%20WorkBuddy-202124?style=flat-square)
![Provider](https://img.shields.io/badge/provider-Right%20Code-2563EB?style=flat-square)
![Model](https://img.shields.io/badge/model-gpt--image--2-16A34A?style=flat-square)

[GitHub 仓库](https://github.com/yfpgle-glitch/rightcode-imagegen) · 中文 · [English](README_EN.md)

</div>

---

## 安装 Skill

需要 Python 3。没有的话，可以直接让 Codex、Claude Code 或 WorkBuddy 帮你安装。

### Codex / Claude Code

把这句话发给 Codex 或 Claude Code：

```text
请把这个仓库根目录作为 Skill 安装：
https://github.com/yfpgle-glitch/rightcode-imagegen
```

安装后，如果没有识别，重新打开一个任务或会话。

### WorkBuddy

1. [下载 Skill 压缩包](https://github.com/yfpgle-glitch/rightcode-imagegen/archive/refs/heads/main.zip)。
2. 在 WorkBuddy 中打开“添加技能”，选择“上传技能”。
3. 上传刚刚下载的压缩包。

## 创建 API Key

1. [注册 Right Code](https://www.rightapi.ai/register?aff=9ec111f0) 并登录。（使用此链接注册，每次充值均可赠送 5% 额外额度。）
2. 打开“令牌管理”。
3. 点击“创建密钥”。

不知道怎么操作，可以查看 [Right Code 官方 API Key 教程](https://docs.rightapi.ai/docs/rc_quick_start/apikey.html)。

## 配置 API Key

安装完成后，对 Codex、Claude Code 或 WorkBuddy 说：

```text
帮我配置 Right Code API Key。
```

工具会打开一个隐藏输入框。粘贴 API Key，然后确认。输入时不会显示 Key。

## 使用

直接告诉当前工具你想要什么：

- `使用 Right Code 生成一张电影感的 16:9 图片。`
- `使用 Right Code 修改这张图片。`
- `使用 Right Code 生成三种不同方案。`
- `继续处理 Right Code 任务 task_example。`

默认使用 `gpt-image-2`、`16:9` 和 `1K`。你也可以指定其他比例或分辨率。

每张图片会单独提交。一次生成多张图片，可能产生多次费用。

## CallAI 备用（统一入口）

默认仍使用 Right Code。现在无需安装 relay-imagegen，即可在同一入口选择 CallAI：

```bash
python3 scripts/generate_image.py --provider callai --list-models
python3 scripts/generate_image.py --provider callai --prompt "一只橘猫" --quote
python3 scripts/generate_image.py --provider callai --prompt "一只橘猫"
```

读取 `CALLAI_API_KEY` 或 `~/.config/callai/api_key`。仅接通 Media API 文生图，默认 gpt-image-2 / 1K / medium；编辑仍走 Right Code。两者复用项目 `output/images/`、提示词记录和原图校验。CallAI 下载失败可用返回检查点文件名中的 ID 配合 `--resume-task-id` 恢复；请求结果未知时不自动重提。不会静默切换供应商，也未加入其他中转站。

