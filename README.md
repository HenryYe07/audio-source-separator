# audio-source-separator

在 Apple Silicon Mac 上执行人声与伴奏双音轨分离的可执行 Skill。按扒谱或翻唱需求选择模型，默认输出无损 WAV。

仅使用以下两个模型：

| 目标 | 模型 |
|---|---|
| 保留乐器细节，适合扒谱 | MelBand Roformer Kim Inst V1 (E) Plus — unwa |
| 优先清除人声，适合翻唱 | BS Roformer Instrumental Resurrection — unwa |

不提供钢琴、吉他、鼓等独立乐器分轨。

## 安装前准备

- Apple Silicon Mac；已在 Apple M4、16 GB 内存、macOS 15.7.3 上实测。
- 原生 arm64 Python 3.11、Git，以及 FFmpeg。
- 首次安装和模型下载需要联网；本机执行需要文件与命令行权限。

如果已经安装 [Homebrew](https://brew.sh)，可用下面的命令准备缺少的依赖；已有依赖可跳过对应项：

```bash
brew install python@3.11 ffmpeg
```

在终端检查：

```bash
python3.11 --version
python3.11 -c 'import platform; print(platform.machine())'
ffmpeg -version
git --version
```

Python 应为 3.11，架构应显示 `arm64`。若显示 `x86_64`，请使用原生终端和 arm64 Python，避免通过 Rosetta 运行。

## 安装到 Codex

在终端运行：

```bash
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/HenryYe07/audio-source-separator.git \
  "$HOME/.agents/skills/audio-source-separator"
python3.11 "$HOME/.agents/skills/audio-source-separator/scripts/setup.py"
```

如果目标文件夹已经存在，请使用已有安装，不要覆盖。上述位置是 Codex 的用户级 Skill 目录，参见 [OpenAI 官方文档](https://developers.openai.com/codex/skills/)。重新打开会话；若仍未显示，重启 Codex。

`setup.py` 会在 Skill 内创建独立 `.venv/`、安装锁定的 Python 依赖并检查 MPS。不会修改系统 Python 或卸载 UVR5。FFmpeg 缺失且已有 Homebrew 时，脚本会尝试自动安装；没有 Homebrew 时会报告缺失前提。无需手动激活虚拟环境。

预检结果中的 `mps_available: true` 表示可使用 Apple GPU；不可用时会明确说明，默认处理可改用 CPU。

## 模型下载与存放

首次处理时只下载所选模型，之后复用。也可以提前下载全部两个模型：

```bash
python3.11 "$HOME/.agents/skills/audio-source-separator/scripts/model_manager.py" --model both
```

两份权重合计约 1.1 GB，Python 依赖还会占用额外磁盘空间。目录布局为：

```text
audio-source-separator/
  SKILL.md
  agents/
  scripts/
  references/
  tests/
  models/     # 两个指定模型及配置，与 Skill 本体放在一起
  .venv/      # 本 Skill 专用 Python 环境
```

模型首次下载后验证固定 SHA-256。正常重复处理不联网检查模型，也不会重复下载。Git 仓库和安装 ZIP 均不包含权重或虚拟环境。搬动完整文件夹时可一起保留 `models/`；虚拟环境会在新位置重新创建。

## 使用

在 Codex 中提供音频文件或本机路径，例如：

```text
使用 $audio-source-separator 处理 /Users/你的用户名/Music/song.m4a，
我要保留乐器细节的扒谱伴奏。
```

也可以说“我要尽可能干净的翻唱伴奏”或“两个模型都处理一遍，我想对比”。只说“提取伴奏”时，Skill 会先询问更重视乐器完整度还是伴奏干净程度。

直接用终端处理也可以；把示例音频路径换成实际路径：

```bash
# 扒谱：优先保留乐器
python3.11 "$HOME/.agents/skills/audio-source-separator/scripts/separate.py" \
  "/absolute/path/song.m4a" --goal detail

# 翻唱：优先清除人声
python3.11 "$HOME/.agents/skills/audio-source-separator/scripts/separate.py" \
  "/absolute/path/song.m4a" --goal clean

# 两模型分别处理
python3.11 "$HOME/.agents/skills/audio-source-separator/scripts/separate.py" \
  "/absolute/path/song.m4a" --model both
```

支持 WAV、FLAC、MP3、M4A、AIFF。多个文件可依次放在同一命令中；传入目录时批量处理其中直接包含的音频，不递归处理子目录。使用 `--output "/absolute/path/results"` 指定输出根目录。

默认保存到原音频所在目录：

```text
output/song_name/
  instrumental.wav
  vocals.wav
  result.json
```

两个模型比较时分别保存在歌曲目录内的 `detail/`、`clean/`。同名或重复任务自动添加序号，避免覆盖。

输出为 32-bit float WAV，并检查解码、时长、采样率、声道和异常空白。模型内部固定 44.1 kHz，其他输入采样率会在内部转换后恢复输出采样率；单声道输出仍为单声道。默认优先 MPS，设备异常时允许回退 CPU 并报告原因。

## ZIP 与 ChatGPT

拿到 `audio-source-separator.zip` 后，可解压，将里面的 `audio-source-separator/` 文件夹放入上述 Skill 目录，再运行其 `scripts/setup.py`。不要将外层包装目录误放进 Skill 目录。

若使用的 ChatGPT 客户端提供 Skill ZIP 导入功能，可使用该标准 Skill 包。**本项目尚未验证 ChatGPT 客户端实际导入**；导入也不代表获得 Mac 的本地执行权限。只有远程云端沙箱时，不能使用你 Mac 的 MPS，应通过本机 Codex 或终端执行。

## 更新与检查

通过 Git 安装后可更新源码，模型缓存会保留：

```bash
git -C "$HOME/.agents/skills/audio-source-separator" pull --ff-only
python3.11 "$HOME/.agents/skills/audio-source-separator/scripts/setup.py"
```

需要重新校验已有权重时：

```bash
python3.11 "$HOME/.agents/skills/audio-source-separator/scripts/model_manager.py" --model both --verify
```

`--verify` 只检查本地文件，缺失或损坏时会报错。完整测试范围、已验证项目与未验证限制见 [验收记录](references/test-report.md)；准确模型来源与校验信息见 [模型说明](references/models.md)。
