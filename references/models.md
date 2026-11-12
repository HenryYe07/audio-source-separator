# 两模型来源与运行约束

核实日期：2026-11-12。机器读取的文件名、下载地址与 SHA-256 唯一来源为同目录 `models.json`。

| 选择 | 完整模型 | 权重 | 配置 |
|---|---|---|---|
| detail / A | MelBand Roformer Kim Inst V1 (E) Plus — unwa | `melband_roformer_inst_v1e_plus.ckpt` | `config_melbandroformer_inst.yaml` |
| clean / B | BS Roformer Instrumental Resurrection — unwa | `bs_roformer_instrumental_resurrection_unwa.ckpt` | `config_bs_roformer_instrumental_resurrection_unwa.yaml` |

名称和文件映射交叉核实自 [python-audio-separator 模型清单](https://github.com/nomadkaraoke/python-audio-separator/blob/main/audio_separator/models.json) 和 [UVR5-UI 模型来源](https://github.com/Eddycrack864/UVR5-UI/blob/main/assets/models.json)。下载优先使用 python-audio-separator 的 [model-configs 发布资产](https://github.com/nomadkaraoke/python-audio-separator/releases/tag/model-configs)，网络故障时仅回退同名文件的 [UVR5-UI 维护者 Hugging Face 镜像](https://huggingface.co/Eddycrack864/audio-separator-models/tree/main/roformers)。两镜像都必须匹配相同的固定 SHA-256。

SHA-256 提取自 `audio-separator==0.48.0` 官方 PyPI wheel 内的 `audio_separator/model-checksums.json`。不在运行时读取可变的远程模型目录，也不加载其他模型。权重下载后原子落盘，写本地校验收据；正常运行对比本地大小和修改时间，显式 `--verify` 可重新哈希。模型内容、配置或来源更新需要维护者重新验证，不能自动更换模型版本。

两个原配置的目标均为 `other`（伴奏），同时声明 `vocals`，均为立体声 44100 Hz、STFT hop 441。MelBand 的 `inference.dim_t=1101`，对应 485100 采样点（11 秒）；BS 的 `dim_t=1700`，对应 749259 采样点（约 16.99 秒）。保留 YAML 的 overlap=2（50% 窗口重叠）、batch=1、float32、无 TTA/音高变换。BS 原 batch=2 在本运行器降至 1；上游 Roformer 路径本身逐窗推理。

推理复用上游 [MDXCSeparator.demix](https://github.com/nomadkaraoke/python-audio-separator/blob/main/audio_separator/separator/architectures/mdxc_separator.py)，用受限的本地 Separator 子类加载模型，绕过上游在线目录。直接 demix 避免上游默认峰值归一化；伴奏来自模型、人声为混音残差。流式磁盘处理每次 30 秒核心加左右各两模型窗口上下文，保留核心并拼接；这控制长文件缓冲区，不能保证与整首一次推理逐采样相同。长曲拼接听感需要另行评估。

MPS 通过 PyTorch 实测检测；设置单进程 MPS 分配上限为推荐工作集的 55%，并按块清空缓存。统一内存还由系统、CPU 和其他应用共享，因此不能对任意输入和系统负载承诺总内存严格小于 16 GB；MPS 内存不足时释放整个子进程并重试 CPU，不缩短训练窗口。`PYTORCH_ENABLE_MPS_FALLBACK=1` 允许部分不支持算子在 CPU 执行，整任务的 MPS 异常另有 CPU 重试。CPU 可能明显更慢。

环境固定原生 Python 3.11、audio-separator[cpu] 0.48.0、PyTorch 2.13.0；cpu extra 安装的是 ONNX Runtime CPU 依赖，不会禁用 PyTorch MPS。上游包包含其他架构代码和依赖，但本工具不下载或调用其他模型。

所有输出 FLOAT WAV 保留预测峰值而不额外限幅；超过 0 dBFS 的 float 样本可保留，播放或转整数 PCM 时应由用户决定增益。验证整段解码与形状/能量，不代表音乐音质评估。模型许可证和上游软件许可仍适用；安装包不重新分发模型权重或上游源码。
