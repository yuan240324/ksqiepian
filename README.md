# ksqiepian — 快手直播回放提取 + 自动切片工具箱

从快手（Kuaishou）直播分享口令 / 短链出发，**解析拿到官方直播回放**，下载 HLS 分片、拼接、重封装为可播放的 MP4，做完整性验证，再自动剪出精彩片段。

> 本仓库只做「已公开分享的直播回放」的抓取与格式处理，用于个人归档与故障恢复。
> 不涉及登录态抓取、不绕过任何付费或权限控制。

---

## 1. 为什么会有这个项目

一次直播录制过程中，本地录制文件遭遇 NTFS MFT 记录损坏，1.65 GB 的 `.ts` 文件在文件系统中能看到尺寸、却无法以任何方式读取（`CreateFileW` 返回 `ERROR_FILE_NOT_FOUND`）。

坏盘排查与数据恢复全部失败后，最终方案是**绕过本地文件，直接从快手官方拉取这场直播的回放**。本仓库沉淀的就是这条可用链路。

---

## 2. 提取链路总览

```
分享口令/短链
   │  ##X56ZfKJb622Z1i7##
   ▼
[1] 短链解析  resolve_ks.py          跟随 302 → 拿到 fw/playback/<id>?subBiz=LIVE_PLAYBACK
   ▼
[2] 回放页抓取 extract_playback.py   拉 HTML → 正则捞出 m3u8 / mp4 直链
   ▼
[3] 回放挑选  pick_replay.py         去重 + 按时长/清晰度排序 → 选中目标 + 试拉 manifest
   ▼
[4] 分片下载  dl_replay.py           8 线程 + 断点续传，逐片写盘
   ▼
[5] 二进制拼接                       1293 个 .ts 顺序拼接 → merged.ts
   ▼
[6] 重封装    remux_full.py          PyAV 透传（不解码）TS → MP4，8 秒完成
   ▼
[7] 完整性验证 verify/*.py           关键帧分布 / 音视频漂移 / 音频采样点数
   ▼
快手直播回放_<主播ID>_<日期>.mp4
   ▼
[8] 精彩片段分析 analyze.py          抽帧找画面突变 + 按秒算音频能量
   ▼
[9] 自动切片    make_clips.py        打分排序 → 去重 → 选 12 段 → stream-copy 切割
   ▼
[10] 切片校验   verify_clips.py      逐段解码音视频，检查静音 / 漂移
   ▼
clips/clip_01_....mp4  ...  clip_12_....mp4
```

---

## 3. 环境要求

| 项 | 版本 / 说明 |
| --- | --- |
| Python | 3.10+ |
| PyAV | `pip install av`（自带完整 ffmpeg 库，**不需要系统装 ffmpeg**） |
| 系统 ffmpeg | **不需要**。本机自带的精简版 ffmpeg 只有 9 个 demuxer / 2 个 muxer / 1 个编码器，无法处理本任务 |
| 网络 | 能访问 `v.kuaishou.com`、`alivod.a.yximgs.com`、`pypi.tuna.tsinghua.edu.cn` |

装 PyAV（国内建议走清华源）：

```powershell
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple av
```

> **关键教训**：不要用系统自带的精简 ffmpeg。它在 5 个地方连续失败（见 `docs/05-踩坑记录.md`）。
> PyAV 的 `add_stream_from_template()` + 包级透传一次成功。

---

## 4. 快速开始

### 4.1 一键跑通（推荐）

`ks_extract/run_pipeline.py` 把 step 1-4 + step 6 串成了一条命令：

```powershell
python ks_extract/run_pipeline.py "##X56ZfKJb622Z1i7##" "G:\ksrec\replay"
```

输入可以是**分享口令 / 短链 / 裸 token** 三种任一形态。脚本会自动解析、抓页、
挑选 `GameAvcHd` 高清源、多线程下载、拼接、重封装，最后打印验证命令。

```text
[19:31:02] step1 解析口令/短链 ...
[19:31:03]   从口令提取 token = X56ZfKJb622Z1i7
[19:31:04]   FINAL = https://v.kuaishou.com/fw/playback/1499544558?...
[19:31:04]   回放 ID = 1499544558
[19:31:04]   已确认 subBiz=LIVE_PLAYBACK（直播回放）
[19:31:05] step2 抓取回放页 ...
[19:31:06]   HTML 147478 bytes -> G:\ksrec\replay\playback_body.html
[19:31:06] step3 提取并挑选 m3u8 ...
[19:31:06]   找到 5 条唯一 m3u8
[19:31:06]     [5] dur=86.1 min clarity=...
[19:31:06]  选中: .../JsQSVN0Ra3Q_GameAvcHdL1Lto...m3u8
[19:31:07] step4 下载分片 ...
[19:31:07]   manifest 172045 bytes, 1293 分片
...
[19:35:41]  完成 1293/1293，失败 0，共 944.4 MB
[19:35:42]  首片 TS sync 抽检 = 50/50
[19:35:45] step5 二进制拼接 ...
[19:35:48]  拼接 1293 片 -> G:\ksrec\replay\merged.ts (944.4 MB, 3s)
[19:35:48]  拼接结果 TS sync 抽检 = 20/20
[19:35:49] step6 PyAV 透传重封装 ...
[19:35:57]   DONE v=154916 a=111235 8s -> 901.2 MB
```

### 4.2 分步执行（便于排障）

```powershell
# 1) 解析口令 / 短链
python ks_extract/resolve_ks.py "https://v.kuaishou.com/f/X56ZfKJb622Z1i7"

# 2) 抓回放页（把上一步的 FINAL 里的 playback id 填进脚本顶部 URL）
python ks_extract/extract_playback.py

# 3) 列出所有回放并按需选取
python ks_extract/pick_replay.py

# 4) 下载分片（把选中的 m3u8 填进 dl_replay.py 顶部 M3U8）
python ks_extract/dl_replay.py

# 5) 拼接（见 docs/03-下载与拼接.md）
# 6) 重封装
python ks_extract/remux_full.py

# 7) 验证
python verify/verify_full.py
python verify/verify_audio.py
python verify/verify_timeline.py
```

---

## 5. 自动切片

拿到成品 MP4 之后，用 `clipper/` 里的脚本自动剪出精彩片段。

```powershell
# 1) 分析全片：找画面突变 + 音频高能量秒（约 12 分钟，只做一次）
python clipper/analyze.py

# 2) 预览切片计划（不实际切割）
python clipper/make_clips.py --list

# 3) 实际切割（stream-copy，12 段只要 3 秒）
python clipper/make_clips.py

# 4) 校验每一段的音视频是否完好
python clipper/verify_clips.py

# 5) 清理旧选区残留（改过选区参数后必跑）
python clipper/clean_clips.py

# 6) 画面查重（两两比缩略图签名，确认无近似重复片段）
python clipper/check_diversity.py

# 7) 给某段加文字：标题条 + 飘屏弹幕 + 结尾卡片（重编码）
python clipper/overlay_text.py
```

打分逻辑：`画面突变幅度` + 附近 `高能量秒数`，另外把连续 3 秒以上的高能量段
单独作为高权重事件；取窗口时要求起点间隔 ≥ 90s，并按 10 分钟分区每区最多选 1 段，
再加**画面指纹去重**（48x36 灰度签名），防止「同一个商店/大厅界面」被连环选中。

```text
========================================================================
源       : 快手直播回放_YyXx-828924_20260916.mp4
时长     : 86.10 min
场景变化 : 12 处 / 高能量秒 571 个
计划切片 : 12 段 x 45s
========================================================================
  [01] 00:01:51 ~ 00:02:36  (45s, score=1.100)
  [02] 00:05:31 ~ 00:06:16  (45s, score=1.000)
  ...
  [12] 01:23:44 ~ 01:24:29  (45s, score=0.351)
  [01] clip_01_000151.mp4  v=1381 a=980  9.8 MB
  ...
完成 12/12，用时 3s
```

验证输出：

```text
[OK ] clip_01_000151.mp4   9.8MB v= 1381( 46.0s) a=  978( 45.4s) pk=1.023 drift=0.64s
[OK ] clip_02_000531.mp4   8.2MB v= 1381( 46.2s) a=  978( 45.4s) pk=0.907 drift=0.85s
...
files=12  bad=0  total=553s (9.2 min)
```

画面查重输出（近似重复 0 对 = 12 段画面互不相同）：

```text
共 12 个缩略图，两两对比中 ...
对比 66 对: 正常 56 / 相似 10 / 近似重复 0
```

详细原理与 4 个 stream-copy 大坑见 [`docs/07-自动切片.md`](docs/07-自动切片.md)。

---

## 6. 文档

| 文档 | 内容 |
| --- | --- |
| [`docs/01-快速开始.md`](docs/01-快速开始.md) | 从零跑通全流程 |
| [`docs/02-链接解析.md`](docs/02-链接解析.md) | 分享口令 / 短链 → 回放页 URL 的解析原理 |
| [`docs/03-下载与拼接.md`](docs/03-下载与拼接.md) | m3u8 解析、多线程分片下载、断点续传、TS 拼接 |
| [`docs/04-重封装与验证.md`](docs/04-重封装与验证.md) | PyAV 透传重封装、三项完整性验证 |
| [`docs/05-踩坑记录.md`](docs/05-踩坑记录.md) | 精简版 ffmpeg 的坑、PyAV API 差异、编码问题 |
| [`docs/06-故障背景.md`](docs/06-故障背景.md) | NTFS MFT 损坏排查与为什么转向官方回放 |
| [`docs/07-自动切片.md`](docs/07-自动切片.md) | 精彩片段打分、stream-copy 切割、时间戳归零 |

---

## 7. 实测结果（2026-09-16）

```text
主播          王者荣耀轩妹妹（圆梦主播）  YyXx-828924
回放 ID       1499544558
m3u8 分片     1293 个
下载体积      944.4 MB
成品          901.2 MB  MP4
时长          86 分 06 秒 (5165.8 s)
分辨率        1280x960 @ 30 fps
编码          视频 H.264 / 音频 AAC 44100 Hz 立体声
关键帧        2637 个，无 >20s 空洞
音视频尾部漂移 0.08 s
── 自动切片 ────────────────────────
产出片段      12 段 x 46s = 553s (9.2 min)
切割耗时      3 秒
校验          12/12 通过，无静音、无漂移
画面查重      66 对对比，近似重复 0 对
```

---

## 8. 目录结构

```text
ksqiepian/
├── README.md
├── docs/                 说明文档
├── ks_extract/           提取链路脚本（step 1-4, 6）
│   ├── run_pipeline.py   ★ 一键跑通（推荐入口）
│   ├── resolve_ks.py
│   ├── extract_playback.py
│   ├── pick_replay.py
│   ├── dl_replay.py
│   ├── remux_full.py
│   ├── inspect_ts.py
│   └── test_dl.py
├── clipper/              自动切片脚本（step 8-10）
│   ├── analyze.py        抽帧找画面突变 + 按秒算音频能量
│   ├── make_clips.py     ★ stream-copy 切割（--list 只预览）
│   ├── verify_clips.py   逐段校验音视频
│   ├── clean_clips.py    清理旧选区残留
│   ├── check_diversity.py 缩略图两两查重
│   └── overlay_text.py   片段叠加标题条/弹幕/结尾卡片（重编码）
├── verify/               完整性验证脚本
│   ├── verify_full.py
│   ├── verify_audio.py
│   └── verify_timeline.py
├── scripts_ps/           拼接 / 排障用的 PowerShell 脚本
└── config.example.ini    一次真实运行的完整参数（复现对照用）
```

---

## 9. 免责声明

本项目仅用于**个人对已公开分享内容的技术归档**，以及本地存储故障后的数据补救。
使用者需自行确保其行为符合当地法律法规与平台服务条款。请勿用于批量抓取、二次分发或任何商业用途。
