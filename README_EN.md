<div align="center">

# Right Code Image

**Generate and edit images with Right Code in Codex, Claude Code, and WorkBuddy**

![Agents](https://img.shields.io/badge/agents-Codex%20%7C%20Claude%20Code%20%7C%20WorkBuddy-202124?style=flat-square)
![Provider](https://img.shields.io/badge/provider-Right%20Code-2563EB?style=flat-square)
![Model](https://img.shields.io/badge/model-gpt--image--2-16A34A?style=flat-square)

[GitHub repository](https://github.com/yfpgle-glitch/rightcode-imagegen) · [中文](README.md) · English

</div>

---

## Install the Skill

Python 3 is required. If it is missing, ask Codex, Claude Code, or WorkBuddy to install it.

### Codex / Claude Code

Send this message to Codex or Claude Code:

```text
Install the root of this repository as a Skill:
https://github.com/yfpgle-glitch/rightcode-imagegen
```

After installation, open a new task or session if the Skill is not detected.

### WorkBuddy

1. [Download the Skill archive](https://github.com/yfpgle-glitch/rightcode-imagegen/archive/refs/heads/main.zip).
2. In WorkBuddy, open **Add Skill** and select **Upload Skill**.
3. Upload the archive you downloaded.

## Create an API key

1. [Register with Right Code](https://www.rightapi.ai/register?aff=9ec111f0) and sign in. (Register through this link to receive 5% extra credit on every top-up.)
2. Open **Token Management**.
3. Select **Create Key**.

For more help, read the [official Right Code API key guide](https://docs.rightapi.ai/docs/rc_quick_start/apikey.html).

## Configure the API key

After installation, tell Codex, Claude Code, or WorkBuddy:

```text
Configure my Right Code API key.
```

The tool will open a hidden input box. Paste the API key and confirm. The key is hidden while you type.

## Use the Skill

Tell the current tool what you want:

- `Use Right Code to generate a cinematic 16:9 image.`
- `Use Right Code to edit this image.`
- `Use Right Code to generate three different versions.`
- `Resume the Right Code task task_example.`

The defaults are `gpt-image-2`, `16:9`, and `1K`. You can ask for another aspect ratio or resolution.

Each image is submitted separately. Generating several images may result in several charges.

## CallAI fallback in the same client

Right Code remains the default. Select `--provider callai` for the Media API generation adapter; no relay-imagegen installation is required. Use `--list-models` for a free check, or `--prompt "An orange cat" --quote` for pricing without generation. Credentials come from `CALLAI_API_KEY` or `~/.config/callai/api_key`.

Defaults: gpt-image-2, 1K, medium. Editing remains Right Code-only. Both adapters share the project-local output layout and image validation. CallAI checkpoints allow download recovery with `--resume-task-id` when the completed response was saved. Unknown submission outcomes are not automatically resubmitted. Providers are never silently switched.

