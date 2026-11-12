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

仅在缺少音频文件或可访问路径时请求提供音频/路径。直接使用已有文件；支持 WAV、FLAC、MP3、M4A、AIFF。无需用户填写推理参数、采样率或输出位置。

每个新处理请求若尚未明确输出格式，先询问并等待回答：**输出需要什么格式？默认与源文件格式和参数一致，也可选择 WAV、FLAC、MP3、M4A 或 AIFF。** 用户说“默认”“和原文件一样”时使用 `--format source`；已明确指定格式则直接采用，不重复询问。默认选项不等于用户已作答。目标、格式或文件同时缺失时合并询问，避免多轮重复。

## 执行

将 `<skill>` 替换为本 SKILL.md 所在文件夹的绝对路径。路径始终正确引用，不把用户文本拼接为 shell 代码。

```bash
python3.11 "<skill>/scripts/separate.py" "/absolute/path/song.m4a" --goal detail
python3.11 "<skill>/scripts/separate.py" "/absolute/path/song.wav" --model clean
python3.11 "<skill>/scripts/separate.py" "/absolute/path/song.wav" --model both
python3.11 "<skill>/scripts/separate.py" "/absolute/path/song1.flac" "/absolute/path/song2.mp3" --goal clean
```

用户明确指定格式时添加 `--format wav` 等参数，默认 `--format source`。用户明确指定输出根目录时添加 `--output "/absolute/path/results"`。目录输入只处理其直接子文件，不递归处理既有输出。默认结果为原文件目录的 `output/song_name/{instrumental.<源扩展名>,vocals.<源扩展名>,result.json}`；双模型结果在歌曲目录下分 `detail/` 和 `clean/`；重复名称自动加序号。批量默认对每个文件分别沿用自己的源格式。

脚本自动创建 Skill 内独立 `.venv/`，安装固定依赖，只将选定模型及 YAML 下载至 Skill 内 `models/`。不要调用上游默认 CLI（默认模型不在白名单内），不要另设外部模型缓存。首次下载验证上游发布的 SHA-256；正常复用不访问网络，不反复计算大文件哈希。怀疑损坏时运行 `scripts/model_manager.py --model detail --verify`，校验失败先报告文件及原因。

环境预检可运行 `python3.11 "<skill>/scripts/setup.py"`。FFmpeg 缺失且 Homebrew 可用时自动安装；没有 Homebrew 时报告缺失前提，要求先安装 FFmpeg。不修改系统 Python 或 UVR5。模型、虚拟环境和锁文件都属于本 Skill；移动文件夹后虚拟环境会在新位置自动重建，模型继续复用。

优先确保本机 GPU 可访问：预检不仅检测 MPS，还实际提交小型 GPU 矩阵运算，成功时 `mps_compute_verified=true`。若 `mps_built=true` 但不可用，先排查当前命令执行沙箱/Metal 权限；使用宿主提供的正常授权流程，在可访问本机 GPU 的执行环境中重试预检，不自行绕过沙箱。不能据此直接认定这台 Mac 不支持 GPU，也不要未经说明就启动耗时 CPU 分离。仍不可用时报告原因，明确用户是否要求 GPU；明确要求 GPU 的任务使用 `--device mps`，不可访问或推理失败即报错。普通任务可使用默认 `--device auto` 优先 MPS 并允许明确告知后的 CPU 回退。无需让用户填写设备参数。

按批次顺序处理，每个模型在独立子进程中加载与释放。默认 auto 优先 MPS；设备不可用或 MPS 推理失败时明确说明 CPU 回退及原因。显式 `--device mps` 不会将整任务自动回退 CPU。运行开始时会显示执行设备，JSON `runtime.device` 和 `runtime.precision` 记录模型真实设备与精度；确认报告的设备，不能把 CPU 处理说成 GPU 加速。读取脚本 JSON 的 `success`、`notices` 和 `validation`，退出码非零或任一失败项都不能报告全部成功。内部运行日志留在临时文件，不向用户粘贴长日志；失败时保留原因的简要说明。

默认沿用源文件格式、采样率、声道及可读取的 PCM 位深或音频码率；可显式输出 WAV、FLAC、MP3、M4A 或 AIFF。MP3/AAC 需要重新编码，按源平均码率尽量匹配，不能完全复刻 VBR 控制或私有编码参数；码率未知时使用 192 kbps。M4A 源为 ALAC 时保留 ALAC；FLAC 导出支持 16/24-bit。不要将 MP3/AAC 输出称作无损。两模型训练采样率均为 44.1 kHz，其他采样率需要内部重采样并恢复到原采样率，此时告知用户；恢复采样率不代表恢复模型未保留的高频。单声道内部双声道推理后恢复单声道；多于两声道明确报告不支持。

## 能力边界与完成

唯一分离能力是人声/伴奏双音轨。不要询问或提供钢琴、吉他、贝斯、鼓等独立分轨选项。用户明确要求独立乐器分轨时，说明当前两模型不能可靠完成，不下载替代模型。

保留模型训练窗口与重叠，不自动二次分离，不附加 EQ、压缩、降噪或音高修改。人声为原混音减去模型估计的伴奏所得残差，不宣称是独立的纯净人声模型。

只在整首处理、最终编码完成后，分别对两个最终文件做一次可播放性确认：文件存在且可正常解码。内部推理仍按长音频分块以控制内存，但不做逐段核验，也不要求用户确认片段。不检查音质、内容、人声残留、能量、静音或与输入的时长一致性，不试听评分。可播放的静音文件也算通过。模型权重完整性校验继续保留。两条最终音轨都可解码后才发布结果。

完成后简洁报告：模型、成功/失败、所选格式、两条音轨位置，以及实际发生的重采样或 CPU 回退。只确认可播放，不评价音质或内容。

需要核对来源、窗口与已知限制时，读取 [references/models.md](references/models.md)。
