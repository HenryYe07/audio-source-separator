---
name: audio-source-separator
description: 在 macOS Apple Silicon 本机实际执行音乐人声与伴奏分离，用于去人声、提取扒谱或翻唱伴奏、批量处理和两模型效果对比。仅支持指定的 unwa MelBand Inst V1 (E) Plus 与 BS Instrumental Resurrection，不提供独立乐器分轨。
---

使用本 Skill 自带脚本直接处理用户音频。需要本机 macOS arm64、原生 Python 3.11、FFmpeg 与命令行/文件权限；远程 ChatGPT 沙箱不能操作用户 Mac 的 MPS。若当前只有远程执行环境，明确说明此限制，提供本机运行入口，不宣称已处理。ZIP 是标准 Skill 文件包，具体 ChatGPT 客户端是否支持导入和本地执行，取决于客户端能力。

## 确认目标

先理解当前请求，再执行。按以下优先级路由：

1. 明确要求两个模型比较：`--model both`，分别输出，不做融合。
2. 明确指定模型：直接使用；MelBand Roformer Kim Inst V1 (E) Plus — unwa → `--model detail`；BS Roformer Instrumental Resurrection — unwa → `--model clean`。无需再问音质偏好。拒绝白名单之外的模型。
3. 已明确目的：扒谱、钢琴和弦/吉他分析、保留弱音泛音和乐器完整度 → `--goal detail`；干净伴奏、翻唱、尽量清除人声 → `--goal clean`。这些是选择策略，不保证每首歌都有相同效果。
4. 仅说“提取伴奏”“去掉人声”等未指定目标的请求，必须先询问并等待回答：

   **你更希望获得哪种伴奏？**

   **选项 A：乐器更清晰、完整（适合扒谱）**。优先保留乐器细节，尽可能减少乐器被误删，可以接受一定程度的人声残留。默认使用 MelBand Roformer Kim Inst V1 (E) Plus — unwa。

   **选项 B：伴奏更干净（适合翻唱）**。优先清除主唱和人声，尽可能减少人声残留，可以接受一定程度的乐器细节损失。默认使用 BS Roformer Instrumental Resurrection — unwa。

仅在缺少音频文件或可访问路径时请求提供音频/路径。目标和文件同时缺失时合并询问。直接使用已有文件；支持 WAV、FLAC、MP3、M4A、AIFF。无需用户填写推理参数或重复确认格式、采样率、输出位置。

## 执行

将 `<skill>` 替换为本 SKILL.md 所在文件夹的绝对路径。路径始终正确引用，不把用户文本拼接为 shell 代码。

```bash
python3.11 "<skill>/scripts/separate.py" "/absolute/path/song.m4a" --goal detail
python3.11 "<skill>/scripts/separate.py" "/absolute/path/song.wav" --model clean
python3.11 "<skill>/scripts/separate.py" "/absolute/path/song.wav" --model both
python3.11 "<skill>/scripts/separate.py" "/absolute/path/song1.flac" "/absolute/path/song2.mp3" --goal clean
```

用户明确指定输出根目录时添加 `--output "/absolute/path/results"`。目录输入只处理其直接子文件，不递归处理既有输出。默认结果为原文件目录的 `output/song_name/{instrumental.wav,vocals.wav,result.json}`；双模型结果在歌曲目录下分 `detail/` 和 `clean/`；重复名称自动加序号。

脚本自动创建 Skill 内独立 `.venv/`，安装固定依赖，只将选定模型及 YAML 下载至 Skill 内 `models/`。不要调用上游默认 CLI（默认模型不在白名单内），不要另设外部模型缓存。首次下载验证上游发布的 SHA-256；正常复用不访问网络，不反复计算大文件哈希。怀疑损坏时运行 `scripts/model_manager.py --model detail --verify`，校验失败先报告文件及原因。

环境预检可运行 `python3.11 "<skill>/scripts/setup.py"`。FFmpeg 缺失且 Homebrew 可用时自动安装；没有 Homebrew 时报告缺失前提，要求先安装 FFmpeg。不修改系统 Python 或 UVR5。模型、虚拟环境和锁文件都属于本 Skill；移动文件夹后虚拟环境会在新位置自动重建，模型继续复用。

按批次顺序处理，每个模型在独立子进程中加载与释放。自动优先 MPS；设备不可用或 MPS 推理失败时明确说明 CPU 回退及原因。读取脚本 JSON 的 `success`、`notices` 和 `validation`，退出码非零或任一失败项都不能报告全部成功。内部运行日志留在临时文件，不向用户粘贴长日志；失败时保留原因的简要说明。

输出为无损 32-bit float WAV，保持输入声道数和输出采样率。两模型训练采样率均为 44.1 kHz，其他采样率需要内部重采样并恢复到原采样率，此时告知用户；恢复采样率不代表恢复模型未保留的高频。单声道内部双声道推理后恢复单声道；多于两声道明确报告不支持。

## 能力边界与完成

唯一分离能力是人声/伴奏双音轨。不要询问或提供钢琴、吉他、贝斯、鼓等独立分轨选项。用户明确要求独立乐器分轨时，说明当前两模型不能可靠完成，不下载替代模型。

保留模型训练窗口与重叠，不自动二次分离，不附加 EQ、压缩、降噪或音高修改。人声为原混音减去模型估计的伴奏所得残差，不宣称是独立的纯净人声模型。

每次必须检查输出存在、完整解码、时长、采样率、声道、有限数值和异常空白。脚本仅在两音轨都验证成功后发布结果；真实静音音轨也可能被保守地判为异常，需人工核对，不伪造音频代替。

完成后简洁报告：模型、成功/失败、两条音轨位置，以及实际发生的重采样或 CPU 回退。文件有效性检查不能证明音乐分离质量，勿声称自动音质评分。

需要核对来源、窗口与已知限制时，读取 [references/models.md](references/models.md)。
