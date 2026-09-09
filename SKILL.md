---
name: rightcode-image
description: Generate or edit images through Right Code, or generate images through the CallAI AI fallback. Use when the user selects Right Code, rightapi.ai, right.codes, CallAI, callai, or this skill, or an active image router selects Right Code. Also configure or check Right Code authentication. Do not override an explicit choice of the host's built-in image tool or another provider.
---

# Right Code Image

Use the bundled `scripts/generate_image.py` with Python 3. Right Code is the default; CallAI is the only optional third-party fallback. Do not change Codex `config.toml` to use either route. Resolve scripts relative to this skill, regardless of the current project directory.

## Generate or edit

```bash
python3 scripts/generate_image.py --prompt "一只戴着太空头盔的橘猫"
```

Default: Right Code, `gpt-image-2.5`, `--size 16:9`, `--image-size 1K`.

- Edit through Right Code by adding one `--reference /absolute/path/image.png` per reference.
- Use `--count N` for N sequential single-image tasks. Provider field `n` stays 1.
- **Always provide `--filename` with a descriptive English name** (without extension). 
  - For non-English prompts, automatically generate a short, descriptive English filename based on the prompt content
  - Examples: `--filename "orange-cat-astronaut"`, `--filename "running-dog"`, `--filename "sunset-mountain"`
  - Keep it simple: 2-4 words describing the main subject and action/scene
  - Use lowercase with hyphens, no special characters
  - If the user provides a filename, use it as-is; otherwise generate one from the prompt
- Use `--help` when other arguments are needed.

A request to generate or edit authorizes the requested images. State the selected provider and count briefly, then proceed.

**Primary provider:** Right Code is the default and preferred provider.

**When Right Code fails:**
1. First, attempt to recover the task with `--resume-task-id` if a task_id exists
2. If recovery fails or isn't possible, you have options:
   - Check if CallAI is configured by trying `--provider callai --list-models`
   - If CallAI is available AND the request doesn't use `--reference` (CallAI doesn't support reference editing), you may offer to try CallAI
   - If the user seems frustrated or time-sensitive, proactively suggest CallAI
   - If it's the first failure in a session, briefly explain the situation and ask if they want to try CallAI
   - For subsequent failures in the same session, use your judgment on whether to ask again or just proceed with CallAI

**Fallback guidance, not rules:**
- You're encouraged to help users succeed, not to block them with rigid approval flows
- If a user just wants their image and doesn't care about the provider, switching to CallAI is fine
- If a user explicitly chose Right Code or the request uses features CallAI doesn't support, explain the limitation
- Balance user intent, urgency, and technical constraints — you decide the right approach

**CallAI limitations:**
- No `--reference` support (reference editing must use Right Code)
- May have different model availability

Never silently switch providers without acknowledging it. A brief "Right Code failed, trying CallAI..." is enough.

## CallAI fallback

Only use this section when the user selects CallAI or the fallback is needed.

```bash
# Free model check
python3 scripts/generate_image.py --provider callai --list-models

# Quote only; no image submission
python3 scripts/generate_image.py --provider callai --prompt "一只橘猫" --quote

# Generate
python3 scripts/generate_image.py --provider callai --prompt "一只橘猫"
```

CallAI uses `https://callai.com:8443/media/v1`, its own key, and defaults to `gpt-image-2.5`, `1K`, `medium`. The adapter checks current model capabilities and obtains a quote before submission. Size uses `--image-size`; quality uses `--quality`. `--size` is expressed as a composition request in the prompt, not a guaranteed output ratio. Preserve original pixels; do not silently crop.

Only Media API **generation** is implemented for CallAI. Reference editing is rejected before a request. Do not route to its old ordinary Images API or claim unsupported features. No other fallback providers are included.

## Keys

Read keys internally; never print them or request them in chat.

| Provider | Environment variable | Key file |
|---|---|---|
| Right Code | `RIGHT_CODES_API_KEY` | `~/.config/right-code/api_key` |
| CallAI | `CALLAI_API_KEY` | `~/.config/callai/api_key` |

For Right Code setup, run `python3 scripts/configure_api_key.py`, then `--check`; report status and saved path only. It uses hidden local input. If needed, link to [registration](https://www.rightapi.ai/register?aff=9ec111f0) and [key creation](https://docs.rightapi.ai/docs/rc_quick_start/apikey.html). Local configuration checks do not prove live generation access. Do not generate a paid image solely to check a key unless the user requested a live test.

## Recovery

```bash
python3 scripts/generate_image.py --resume-task-id TASK_ID
python3 scripts/generate_image.py --provider callai --resume-task-id callai-LOCAL_UUID
```

Use the original output root when resuming, including the same explicit `--output-dir` if supplied.

- Right Code resumes remote polling without resubmitting. The client retries transient polling errors with bounded backoff. If no task can be recovered, allow at most three total submissions per intended image under the original request; stop for authentication failures, unexpected cost or an uncertain submission outcome.
- CallAI saves the submission ID and completed response locally. Resume retries saving/downloading an already-saved response without a new paid task. It cannot recover a remote result when the original response never arrived. Do not automatically resubmit an uncertain request. Batches stop on failure, preserving completed outputs.
- Never combine resume with a new prompt, references or multiple outputs.

## Output

Both routes share the existing project-local layout:

```text
<project>/output/images/
  YYYY-MM-DD/YYYYMMDD-HHMMSS-NNN-content.png
  .prompts/YYYY-MM-DD/YYYYMMDD-HHMMSS-NNN-content.md
  .tasks/rightcode/...
  .tasks/callai/...
```

The nearest Git/Mercurial root takes precedence over package markers. With no project root, supply `--output-dir`; never fall back to Downloads, Desktop or agent internal state. An explicit directory keeps hidden `.prompts` and `.tasks` sidecars. Existing artifacts are not deleted. Right Code still finds legacy `generated_images/.tasks/rightcode` checkpoints.

Prompt records contain the provider, model, size, operation, timestamp and full prompt, without secrets or temporary URLs. Task records may contain temporary image URLs for recovery. Generated artifacts are ignored by the managed output root's `.gitignore`.

Read final JSON. Display saved originals and link each image and matching prompt file. Report partial failures accurately; a model listing or quote is not a successful generation. Confirm image format and actual dimensions before reporting a live test as successful.

## Right Code protocol

Keep asynchronous submission to `https://www.rightapi.ai/draw/v1/images/generations` and polling at `https://www.rightapi.ai/v1/tasks/{task_id}`. Preserve `async: true`, `n: 1`, immediate checkpoints, and completed responses containing URL/base64/inline images even without a status. Download original bytes before presenting results.
