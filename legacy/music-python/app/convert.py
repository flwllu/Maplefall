"""基于 PyAV 的转码引擎。

PyAV 通过 pip 安装时自带 FFmpeg 动态库，不需要系统里存在 ffmpeg 可执行文件，
因此在 macOS / Windows 上都能保持一致的转码能力。

引擎覆盖：
    - 音视频探测（流、时长、编码、分辨率、采样率等）
    - 容器 / 编码器选择，直接复制流（remux）或重新编码
    - 裁剪、分辨率、帧率、像素格式、码率控制、预设、GOP、B 帧等视频参数
    - 采样率、声道、码率、音量等音频参数
    - 视频 / 音频滤镜链（标准滤镜 + 自定义 FFmpeg 滤镜表达式）
    - 容器与编码器的自定义 key=value 参数
    - 进度回调与取消
"""

from __future__ import annotations

import os
from fractions import Fraction

import av


class ConvertError(Exception):
    """可展示给用户的转码错误。"""


class ConversionCancelled(Exception):
    """用户取消了转码。"""


# ============================ 编码器与容器 ============================

VIDEO_CODEC_LABELS = {
    "copy": "复制原流（不重编码）",
    "none": "移除视频",
    "libx264": "H.264 / AVC（libx264）",
    "libx265": "H.265 / HEVC（libx265）",
    "h264_videotoolbox": "H.264（VideoToolbox 硬件）",
    "hevc_videotoolbox": "HEVC（VideoToolbox 硬件）",
    "libvpx": "VP8（libvpx）",
    "libvpx-vp9": "VP9（libvpx）",
    "libsvtav1": "AV1（SVT-AV1）",
    "mpeg4": "MPEG-4 Part 2",
    "mjpeg": "Motion JPEG",
    "gif": "GIF",
    "prores_ks": "Apple ProRes",
    "png": "PNG 帧",
    "rawvideo": "Raw Video",
}

AUDIO_CODEC_LABELS = {
    "copy": "复制原流（不重编码）",
    "none": "移除音频",
    "aac": "AAC",
    "libmp3lame": "MP3（libmp3lame）",
    "libopus": "Opus（libopus）",
    "flac": "FLAC（无损）",
    "alac": "ALAC（无损）",
    "pcm_s16le": "PCM 16-bit",
    "pcm_s24le": "PCM 24-bit",
    "pcm_s32le": "PCM 32-bit",
    "pcm_f32le": "PCM 32-bit 浮点",
    "ac3": "AC-3",
    "eac3": "E-AC-3",
    "mp2": "MP2",
    "wmav2": "WMA v2",
}

SUBTITLE_CODEC_LABELS = {
    "copy": "复制字幕",
    "none": "移除字幕",
}

CONTAINER_SPECS = {
    "mp4": {
        "label": "MP4", "ext": ".mp4", "format": "mp4", "kind": "video",
        "video": ["libx264", "libx265", "mpeg4",
                  "h264_videotoolbox", "hevc_videotoolbox"],
        "audio": ["aac", "libmp3lame", "alac", "ac3"],
        "subtitles": ["copy"],
        "faststart": True,
        "note": "兼容性最好，适合网络分发与 Apple 设备。",
    },
    "mov": {
        "label": "MOV", "ext": ".mov", "format": "mov", "kind": "video",
        "video": ["libx264", "libx265", "prores_ks", "mpeg4",
                  "h264_videotoolbox", "hevc_videotoolbox"],
        "audio": ["aac", "alac", "pcm_s16le", "pcm_s24le", "ac3"],
        "subtitles": ["copy"],
        "faststart": True,
        "note": "QuickTime 容器，剪辑与 ProRes 工作流常用。",
    },
    "mkv": {
        "label": "MKV", "ext": ".mkv", "format": "matroska", "kind": "video",
        "video": ["libx264", "libx265", "libvpx-vp9", "libsvtav1", "mpeg4",
                  "mjpeg", "prores_ks"],
        "audio": ["aac", "libmp3lame", "libopus", "flac", "alac",
                  "pcm_s16le", "ac3", "eac3"],
        "subtitles": ["copy"],
        "faststart": False,
        "note": "几乎什么都能装，适合归档与多音轨。",
    },
    "webm": {
        "label": "WebM", "ext": ".webm", "format": "webm", "kind": "video",
        "video": ["libvpx", "libvpx-vp9", "libsvtav1"],
        "audio": ["libopus"],
        "subtitles": ["copy"],
        "faststart": False,
        "note": "Web 友好，VP9 / AV1 + Opus。",
    },
    "avi": {
        "label": "AVI", "ext": ".avi", "format": "avi", "kind": "video",
        "video": ["libx264", "mpeg4", "mjpeg"],
        "audio": ["libmp3lame", "pcm_s16le", "ac3"],
        "subtitles": [],
        "faststart": False,
        "note": "老设备兼容，体积较大。",
    },
    "flv": {
        "label": "FLV", "ext": ".flv", "format": "flv", "kind": "video",
        "video": ["libx264"],
        "audio": ["aac", "libmp3lame"],
        "subtitles": [],
        "faststart": False,
        "note": "直播 / 旧版网页播放器常用。",
    },
    "ts": {
        "label": "MPEG-TS", "ext": ".ts", "format": "mpegts", "kind": "video",
        "video": ["libx264", "libx265", "mpeg4"],
        "audio": ["aac", "mp2", "ac3"],
        "subtitles": [],
        "faststart": False,
        "note": "广播 / 流媒体传输格式。",
    },
    "gif": {
        "label": "GIF", "ext": ".gif", "format": "gif", "kind": "video",
        "video": ["gif"],
        "audio": [],
        "subtitles": [],
        "faststart": False,
        "note": "动图，无音频；建议帧率 10–15、宽度不超过 800。",
    },
    "mp3": {
        "label": "MP3", "ext": ".mp3", "format": "mp3", "kind": "audio",
        "video": [],
        "audio": ["libmp3lame"],
        "subtitles": [],
        "faststart": False,
        "note": "通用有损音频，兼容性最好。",
    },
    "flac": {
        "label": "FLAC", "ext": ".flac", "format": "flac", "kind": "audio",
        "video": [],
        "audio": ["flac"],
        "subtitles": [],
        "faststart": False,
        "note": "无损压缩，适合归档。",
    },
    "wav": {
        "label": "WAV", "ext": ".wav", "format": "wav", "kind": "audio",
        "video": [],
        "audio": ["pcm_s16le", "pcm_s24le", "pcm_s32le", "pcm_f32le"],
        "subtitles": [],
        "faststart": False,
        "note": "未压缩 PCM，体积大但最通用。",
    },
    "m4a": {
        "label": "M4A", "ext": ".m4a", "format": "ipod", "kind": "audio",
        "video": [],
        "audio": ["aac", "alac"],
        "subtitles": [],
        "faststart": False,
        "note": "Apple 生态常用音频容器。",
    },
    "aac": {
        "label": "AAC（裸流）", "ext": ".aac", "format": "adts", "kind": "audio",
        "video": [],
        "audio": ["aac"],
        "subtitles": [],
        "faststart": False,
        "note": "ADTS 裸流，常见于广播与流媒体。",
    },
    "ogg": {
        "label": "OGG", "ext": ".ogg", "format": "ogg", "kind": "audio",
        "video": [],
        "audio": ["libopus"],
        "subtitles": [],
        "faststart": False,
        "note": "开源容器，这里使用 Opus 编码。",
    },
    "opus": {
        "label": "Opus", "ext": ".opus", "format": "opus", "kind": "audio",
        "video": [],
        "audio": ["libopus"],
        "subtitles": [],
        "faststart": False,
        "note": "低码率高音质，语音与网络传输首选。",
    },
    "wma": {
        "label": "WMA", "ext": ".wma", "format": "asf", "kind": "audio",
        "video": [],
        "audio": ["wmav2"],
        "subtitles": [],
        "faststart": False,
        "note": "Windows 传统音频格式。",
    },
    "aiff": {
        "label": "AIFF", "ext": ".aiff", "format": "aiff", "kind": "audio",
        "video": [],
        "audio": ["pcm_s16le", "pcm_s24le", "pcm_f32le"],
        "subtitles": [],
        "faststart": False,
        "note": "Apple 无损 PCM 容器。",
    },
    "mka": {
        "label": "MKA", "ext": ".mka", "format": "matroska", "kind": "audio",
        "video": [],
        "audio": ["flac", "libopus", "aac", "libmp3lame"],
        "subtitles": [],
        "faststart": False,
        "note": "Matroska 纯音频容器，可装无损。",
    },
}

PIX_FMT_CHOICES = [
    "yuv420p", "yuv422p", "yuv444p", "yuv420p10le", "yuv422p10le",
    "yuv444p10le", "nv12", "rgb24", "rgba", "rgb8", "gray", "pal8",
]

SAMPLE_RATES = (8000, 11025, 16000, 22050, 24000, 32000, 44100, 48000,
                88200, 96000, 176400, 192000)

AUDIO_LAYOUTS = [
    ("保持原样", None),
    ("单声道", "mono"),
    ("立体声", "stereo"),
    ("2.1", "2.1"),
    ("3.0", "3.0"),
    ("4.0", "4.0"),
    ("5.0", "5.0"),
    ("5.1", "5.1"),
    ("7.1", "7.1"),
]

CHANNEL_LAYOUTS = {
    1: "mono",
    2: "stereo",
    3: "2.1",
    4: "4.0",
    5: "5.0",
    6: "5.1",
    7: "6.1",
    8: "7.1",
}


def layout_for_channels(channels):
    return CHANNEL_LAYOUTS.get(int(channels or 0), "stereo")

VIDEO_PRESETS = ["ultrafast", "superfast", "veryfast", "faster", "fast",
                 "medium", "slow", "slower", "veryslow"]

VIDEO_TUNES = ["film", "animation", "grain", "stillimage", "fastdecode",
               "zerolatency"]


def _encoder_available(name, kind):
    try:
        av.codec.Codec(name, "w")
        return True
    except Exception:
        return False


def available_video_codecs(container_key):
    spec = CONTAINER_SPECS[container_key]
    return [name for name in spec["video"] if _encoder_available(name, "video")]


def available_audio_codecs(container_key):
    spec = CONTAINER_SPECS[container_key]
    return [name for name in spec["audio"] if _encoder_available(name, "audio")]


def video_pix_fmts(codec):
    try:
        formats = av.codec.Codec(codec, "w").video_formats or []
    except Exception:
        return []
    names = [fmt.name for fmt in formats]
    ordered = [name for name in PIX_FMT_CHOICES if name in names]
    ordered += [name for name in names if name not in ordered]
    return ordered


def audio_sample_formats(codec):
    try:
        formats = av.codec.Codec(codec, "w").audio_formats or []
    except Exception:
        return []
    return [fmt.name for fmt in formats]


def audio_sample_rates(codec):
    try:
        return list(av.codec.Codec(codec, "w").audio_rates or [])
    except Exception:
        return []


def pick_sample_rate(codec, requested):
    """编码器只支持有限采样率时，自动选择最接近的合法值。"""
    rates = audio_sample_rates(codec)
    if not rates:
        return int(requested or 44100)
    requested = int(requested or 44100)
    if requested in rates:
        return requested
    return min(rates, key=lambda rate: abs(rate - requested))


def container_specs():
    return CONTAINER_SPECS


def default_container_for(info):
    has_video = any(stream["type"] == "video" for stream in info["streams"])
    if has_video:
        return "mp4"
    return "mp3"


# ============================ 探测 ============================

def _fps(stream):
    for value in (stream.average_rate, stream.guessed_rate):
        try:
            if value and value > 0:
                return float(value)
        except (TypeError, ZeroDivisionError):
            continue
    return 0.0


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _stream_duration(stream):
    if stream.duration and stream.time_base:
        return float(stream.duration * stream.time_base)
    return 0.0


def probe_media(path):
    """读取媒体信息，返回界面可直接展示的字典。"""
    if not path or not os.path.isfile(path):
        raise ConvertError("文件不存在")
    try:
        container = av.open(path)
    except Exception as error:
        raise ConvertError(f"无法打开文件：{error}") from error

    try:
        duration = 0.0
        if container.duration:
            duration = float(container.duration / av.time_base)
        if duration <= 0:
            durations = [_stream_duration(stream) for stream in container.streams]
            duration = max(durations) if durations else 0.0

        streams = []
        for stream in container.streams:
            context = stream.codec_context
            item = {
                "index": stream.index,
                "type": stream.type,
                "codec": context.name,
                "duration": round(_stream_duration(stream), 3),
            }
            if stream.type == "video":
                item.update({
                    "width": _safe_int(context.width),
                    "height": _safe_int(context.height),
                    "fps": round(_fps(stream), 3),
                    "pix_fmt": context.pix_fmt,
                    "bit_rate": _safe_int(stream.bit_rate or context.bit_rate),
                })
            elif stream.type == "audio":
                item.update({
                    "sample_rate": _safe_int(stream.rate),
                    "channels": _safe_int(getattr(context, "channels", 0)),
                    "layout": layout_for_channels(
                        getattr(context, "channels", 0)),
                    "bit_rate": _safe_int(stream.bit_rate or context.bit_rate),
                })
            elif stream.type == "subtitle":
                item["language"] = (stream.metadata or {}).get("language", "")
            streams.append(item)

        names = (container.format.name or "").split(",")
        return {
            "path": path,
            "format": names[0] if names else "",
            "format_long": container.format.long_name,
            "duration": round(duration, 3),
            "size": os.path.getsize(path),
            "bit_rate": _safe_int(container.bit_rate),
            "streams": streams,
            "metadata": dict(container.metadata or {}),
        }
    finally:
        container.close()


# ============================ 路径 ============================

def default_output_path(src_path, container_key, out_dir=None):
    """根据源文件与目标容器生成输出路径，同后缀时追加“(转换)”避免覆盖。"""
    spec = CONTAINER_SPECS[container_key]
    stem, src_ext = os.path.splitext(os.path.basename(src_path))
    if spec["ext"].lower() == src_ext.lower():
        stem += " (转换)"
    folder = out_dir or os.path.dirname(src_path)
    return os.path.join(folder, stem + spec["ext"])


def parse_time(value):
    """把 "12"、"1:23"、"00:01:23.5" 解析成秒。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parts = text.split(":")
        if len(parts) > 3:
            raise ValueError
        total = 0.0
        for part in parts:
            total = total * 60 + float(part)
        return max(0.0, total)
    except ValueError:
        return None


def format_seconds(seconds):
    seconds = max(0, int(round(seconds or 0)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ============================ 转码 ============================

def _pick_pix_fmt(codec, requested):
    choices = video_pix_fmts(codec)
    if requested and requested in choices:
        return requested
    if codec == "gif":
        return "rgb8"
    if codec == "prores_ks":
        return "yuv422p10le"
    if codec == "png":
        return "rgb24"
    if requested:
        return requested
    if "yuv420p" in choices:
        return "yuv420p"
    return choices[0] if choices else None


def _pick_audio_format(codec):
    formats = audio_sample_formats(codec)
    if not formats:
        return None
    for preferred in ("s16p", "fltp", "s16", "flt", "s32p", "s32"):
        if preferred in formats:
            return preferred
    return formats[0]


def _filter_tokens(expression):
    """用分号分隔滤镜，保留参数中的逗号。"""
    for token in str(expression or "").split(";"):
        token = token.strip()
        if not token:
            continue
        if "=" in token:
            name, args = token.split("=", 1)
        else:
            name, args = token, ""
        name = name.strip()
        if name:
            yield name, args.strip()


def _scale_filters(width, height, mode):
    if not width and not height:
        return []
    w = width or -2
    h = height or -2
    if mode == "fit" and width and height:
        return [
            ("scale", f"w={w}:h={h}:force_original_aspect_ratio=decrease"),
            ("pad", f"w={width}:h={height}:x=(ow-iw)/2:y=(oh-ih)/2:color=black"),
        ]
    return [("scale", f"w={w}:h={h}")]


def _trim_filters(start, end, audio=False):
    if not start and end is None:
        return []
    prefix = "a" if audio else ""
    args = []
    if start:
        args.append(f"start={start:.3f}")
    if end is not None:
        args.append(f"end={end:.3f}")
    return [
        (prefix + "trim", ":".join(args)),
        (prefix + "setpts", "PTS-STARTPTS"),
    ]


def _build_video_graph(stream, vcfg, codec, fps, start, end):
    graph = av.filter.Graph()
    previous = graph.add_buffer(template=stream)
    filters = []
    filters += _trim_filters(start, end)
    filters += _scale_filters(
        vcfg.get("width"), vcfg.get("height"), vcfg.get("scale_mode", "fit"))
    if fps:
        filters.append(("fps", f"fps={fps}"))
    pix_fmt = _pick_pix_fmt(codec, vcfg.get("pix_fmt"))
    if pix_fmt:
        filters.append(("format", f"pix_fmts={pix_fmt}"))
    filters += list(_filter_tokens(vcfg.get("filter")))
    for name, args in filters:
        node = graph.add(name, args)
        previous.link_to(node)
        previous = node
    sink = graph.add("buffersink")
    previous.link_to(sink)
    graph.configure()
    return graph, sink, pix_fmt


def _build_audio_graph(stream, acfg, start, end):
    tokens = list(_trim_filters(start, end, audio=True))
    volume = acfg.get("volume")
    try:
        volume = float(volume) if volume not in (None, "") else 100.0
    except (TypeError, ValueError):
        volume = 100.0
    if abs(volume - 100.0) > 0.01:
        tokens.append(("volume", f"volume={volume / 100.0:.4f}"))
    tokens += list(_filter_tokens(acfg.get("filter")))
    if not tokens:
        return None, None
    graph = av.filter.Graph()
    previous = graph.add_abuffer(template=stream)
    for name, args in tokens:
        node = graph.add(name, args)
        previous.link_to(node)
        previous = node
    sink = graph.add("abuffersink")
    previous.link_to(sink)
    graph.configure()
    return graph, sink


def _apply_video_options(stream, vcfg, codec):
    context = stream.codec_context
    options = {str(k): str(v) for k, v in (vcfg.get("options") or {}).items()}
    preset = vcfg.get("preset")
    if preset:
        if codec == "libvpx-vp9":
            mapping = {
                "ultrafast": "8", "superfast": "7", "veryfast": "6",
                "faster": "5", "fast": "4", "medium": "3",
                "slow": "2", "slower": "1", "veryslow": "0",
            }
            options.setdefault("cpu-used", mapping.get(preset, "3"))
        elif codec == "libsvtav1":
            mapping = {
                "ultrafast": "13", "superfast": "12", "veryfast": "11",
                "faster": "10", "fast": "9", "medium": "8",
                "slow": "6", "slower": "4", "veryslow": "2",
            }
            options.setdefault("preset", mapping.get(preset, "8"))
        elif codec not in ("gif", "png", "mjpeg", "rawvideo"):
            options.setdefault("preset", preset)
    tune = vcfg.get("tune")
    if tune and codec in ("libx264", "libx265"):
        options.setdefault("tune", tune)
    crf = vcfg.get("crf")
    if crf not in (None, ""):
        if codec not in ("h264_videotoolbox", "hevc_videotoolbox"):
            options.setdefault("crf", str(crf))
    if vcfg.get("profile"):
        try:
            context.profile = str(vcfg["profile"])
        except Exception:
            pass
    if options:
        context.options = options
    if vcfg.get("bitrate"):
        context.bit_rate = int(float(vcfg["bitrate"]) * 1000)
    if vcfg.get("maxrate"):
        context.max_bit_rate = int(float(vcfg["maxrate"]) * 1000)
    if vcfg.get("gop"):
        context.gop_size = int(vcfg["gop"])
    if vcfg.get("bframes") not in (None, ""):
        try:
            context.max_b_frames = int(vcfg["bframes"])
        except (TypeError, ValueError):
            pass
    if vcfg.get("threads") not in (None, ""):
        try:
            context.thread_count = int(vcfg["threads"])
        except (TypeError, ValueError):
            pass
    if stream.time_base is not None:
        context.time_base = stream.time_base


def _apply_audio_options(stream, acfg):
    context = stream.codec_context
    if acfg.get("options"):
        context.options = {
            str(k): str(v) for k, v in acfg["options"].items()}
    if acfg.get("bitrate"):
        context.bit_rate = int(float(acfg["bitrate"]) * 1000)


def _stream_end_seconds(stream, fallback):
    value = _stream_duration(stream)
    return value if value > 0 else fallback


def _packet_seconds(packet):
    base = packet.stream.time_base
    if base is None:
        return 0.0
    if packet.pts is not None:
        return float(packet.pts * base)
    if packet.dts is not None:
        return float(packet.dts * base)
    return 0.0


def convert_media(src_path, dst_path, config, progress=None, cancel=None):
    """执行一次转码。

    :param config: 界面收集的参数，详见模块说明。
    :param progress: callable(percent: int)
    :param cancel: threading.Event，置位后尽快中止。
    """
    if os.path.abspath(src_path) == os.path.abspath(dst_path):
        raise ConvertError("输出文件不能与源文件相同")

    try:
        source = av.open(src_path)
    except Exception as error:
        raise ConvertError(f"无法读取源文件：{error}") from error

    output = None
    try:
        info_duration = 0.0
        if source.duration:
            info_duration = float(source.duration / av.time_base)

        start = float(config.get("start") or 0.0)
        duration_limit = config.get("duration")
        if duration_limit in ("", None):
            duration_limit = None
        else:
            duration_limit = float(duration_limit)

        if config.get("shortest"):
            ends = [_stream_end_seconds(stream, info_duration)
                    for stream in source.streams
                    if stream.type in ("video", "audio")]
            if ends:
                shortest = min(ends)
                room = max(0.0, shortest - start)
                duration_limit = room if duration_limit is None \
                    else min(duration_limit, room)
        end_time = start + duration_limit if duration_limit else None
        total = duration_limit or max(0.0, info_duration - start) or 0.0

        video_cfg = config.get("video") or {}
        audio_cfg = config.get("audio") or {}
        subtitle_cfg = config.get("subtitle") or {}

        def find_stream(kind, index):
            for stream in source.streams:
                if stream.type == kind and stream.index == index:
                    return stream
            return None

        video_in = find_stream("video", video_cfg.get("stream"))
        if video_in is None:
            video_in = next(iter(source.streams.video), None)
        audio_in = find_stream("audio", audio_cfg.get("stream"))
        if audio_in is None:
            audio_in = next(iter(source.streams.audio), None)
        subtitle_in = find_stream("subtitle", subtitle_cfg.get("stream"))
        if subtitle_in is None:
            subtitle_in = next(iter(source.streams.subtitles), None)

        video_mode = video_cfg.get("codec") or "none"
        audio_mode = audio_cfg.get("codec") or "none"
        subtitle_mode = subtitle_cfg.get("codec") or "none"

        if video_mode != "none" and video_in is None:
            video_mode = "none"
        if audio_mode != "none" and audio_in is None:
            audio_mode = "none"
        if subtitle_mode != "none" and subtitle_in is None:
            subtitle_mode = "none"

        container_key = config.get("container_key")
        spec = CONTAINER_SPECS.get(container_key, {})
        target_format = config.get("container") or spec.get("format") or "mp4"

        container_options = {
            str(k): str(v)
            for k, v in (config.get("container_options") or {}).items()
        }
        if config.get("faststart") and spec.get("faststart"):
            movflags = container_options.get("movflags", "")
            if "faststart" not in movflags:
                container_options["movflags"] = (
                    (movflags + "+" if movflags else "") + "faststart")

        output = av.open(dst_path, "w", format=target_format,
                         options=container_options or None)
        if config.get("metadata", True):
            try:
                output.metadata.update(source.metadata or {})
            except Exception:
                pass
        if config.get("chapters", True) and source.chapters:
            try:
                output.set_chapters(source.chapters)
            except Exception:
                pass

        plans = []
        video_plan = None
        audio_plan = None

        # -------- 视频流 --------
        if video_mode == "copy" and video_in is not None:
            out_stream = output.add_stream_from_template(video_in)
            video_plan = {"in": video_in, "out": out_stream, "mode": "copy"}
            plans.append(video_plan)
        elif video_mode not in ("none", "copy") and video_in is not None:
            rate = video_cfg.get("fps")
            if not rate:
                rate = _fps(video_in) or 25.0
            out_stream = output.add_stream(video_mode, rate=Fraction(rate))
            width = int(video_cfg.get("width") or
                        video_in.codec_context.width or 0)
            height = int(video_cfg.get("height") or
                         video_in.codec_context.height or 0)
            if width > 0:
                out_stream.width = width
            if height > 0:
                out_stream.height = height
            pix_fmt = _pick_pix_fmt(video_mode, video_cfg.get("pix_fmt"))
            if pix_fmt:
                out_stream.codec_context.pix_fmt = pix_fmt
            _apply_video_options(out_stream, video_cfg, video_mode)
            graph, sink, _ = _build_video_graph(
                video_in, video_cfg, video_mode, rate, start, end_time)
            video_plan = {"in": video_in, "out": out_stream, "mode": "encode",
                          "graph": graph, "sink": sink}
            plans.append(video_plan)

        # -------- 音频流 --------
        if audio_mode == "copy" and audio_in is not None:
            out_stream = output.add_stream_from_template(audio_in)
            audio_plan = {"in": audio_in, "out": out_stream, "mode": "copy"}
            plans.append(audio_plan)
        elif audio_mode not in ("none", "copy") and audio_in is not None:
            sample_rate = pick_sample_rate(
                audio_mode, audio_cfg.get("sample_rate") or audio_in.rate or 44100)
            layout = audio_cfg.get("layout")
            if not layout:
                layout = layout_for_channels(
                    getattr(audio_in.codec_context, "channels", 2))
            out_stream = output.add_stream(
                audio_mode, rate=int(sample_rate), layout=layout)
            _apply_audio_options(out_stream, audio_cfg)
            sample_format = _pick_audio_format(audio_mode)
            resampler = av.AudioResampler(
                format=sample_format, layout=layout, rate=int(sample_rate))
            graph, sink = _build_audio_graph(audio_in, audio_cfg, start, end_time)
            audio_plan = {"in": audio_in, "out": out_stream, "mode": "encode",
                          "graph": graph, "sink": sink,
                          "resampler": resampler, "_first": None}
            plans.append(audio_plan)
        else:
            sample_format = None

        # -------- 字幕流 --------
        if subtitle_mode == "copy" and subtitle_in is not None:
            out_stream = output.add_stream_from_template(subtitle_in)
            plans.append({"in": subtitle_in, "out": out_stream, "mode": "copy"})

        if not plans:
            raise ConvertError("没有可输出的流，请至少保留视频或音频。")

        input_streams = [plan["in"] for plan in plans]
        if start > 0:
            try:
                source.seek(int(start * 1_000_000), backward=True)
            except Exception:
                pass

        def emit(percent):
            if progress:
                progress(max(0, min(99, int(percent))))

        def should_stop():
            return bool(cancel is not None and cancel.is_set())

        def shift_packet(packet, plan):
            if start <= 0:
                return
            stream = plan["in"]
            base = stream.time_base
            if not base:
                return
            offset = int(start / base)
            if packet.pts is not None:
                packet.pts = max(0, packet.pts - offset)
            if packet.dts is not None:
                packet.dts = max(0, packet.dts - offset)

        def drain_video(plan):
            sink = plan["sink"]
            out_stream = plan["out"]
            while True:
                try:
                    frame = sink.pull()
                except (av.error.BlockingIOError, EOFError):
                    break
                for packet in out_stream.encode(frame):
                    output.mux(packet)

        def drain_audio(plan):
            sink = plan["sink"]
            out_stream = plan["out"]
            resampler = plan["resampler"]
            while True:
                try:
                    frame = sink.pull()
                except (av.error.BlockingIOError, EOFError):
                    break
                for resampled in resampler.resample(frame):
                    for packet in out_stream.encode(resampled):
                        output.mux(packet)

        last_time = start if start else 0.0
        for packet in source.demux(*input_streams):
            if should_stop():
                raise ConversionCancelled
            if packet.dts is None:
                continue
            plan = next((p for p in plans if p["in"] is packet.stream), None)
            if plan is None:
                continue

            packet_time = _packet_seconds(packet)
            if packet_time > last_time:
                last_time = packet_time
                if total > 0:
                    emit((last_time - start) / total * 100)

            is_copy = plan["mode"] == "copy"
            if is_copy:
                if end_time is not None and packet_time > end_time:
                    continue
                if start > 0 and packet_time < start - 0.001:
                    continue
            elif end_time is not None and packet_time > end_time + 0.5:
                continue

            if plan["mode"] == "copy":
                if start > 0:
                    shift_packet(packet, plan)
                packet.stream = plan["out"]
                try:
                    output.mux(packet)
                except Exception as error:
                    raise ConvertError(f"封装失败：{error}") from error
                continue

            for frame in packet.decode():
                if should_stop():
                    raise ConversionCancelled
                if plan.get("done"):
                    continue

                if plan is video_plan:
                    try:
                        plan["graph"].push(frame)
                    except av.error.EOFError:
                        plan["done"] = True
                        drain_video(plan)
                        continue
                    drain_video(plan)
                elif plan is audio_plan:
                    if plan["graph"] is not None:
                        try:
                            plan["graph"].push(frame)
                        except av.error.EOFError:
                            plan["done"] = True
                            drain_audio(plan)
                            continue
                        drain_audio(plan)
                    else:
                        for resampled in plan["resampler"].resample(frame):
                            for packet_out in plan["out"].encode(resampled):
                                output.mux(packet_out)

        if should_stop():
            raise ConversionCancelled

        # -------- 收尾 --------
        for plan in plans:
            if plan["mode"] != "encode":
                continue
            if plan is video_plan and video_plan.get("graph") is not None:
                try:
                    video_plan["graph"].push(None)
                except Exception:
                    pass
                drain_video(video_plan)
            if plan is audio_plan:
                if audio_plan.get("graph") is not None:
                    try:
                        audio_plan["graph"].push(None)
                    except Exception:
                        pass
                    drain_audio(audio_plan)
                else:
                    for resampled in (audio_plan["resampler"].resample(None)
                                      or []):
                        for packet_out in audio_plan["out"].encode(resampled):
                            output.mux(packet_out)
            for packet in plan["out"].encode(None):
                output.mux(packet)

        output.close()
        output = None
        if progress:
            progress(100)
    except ConversionCancelled:
        raise
    except ConvertError:
        raise
    except Exception as error:
        raise ConvertError(str(error) or error.__class__.__name__) from error
    finally:
        if output is not None:
            try:
                output.close()
            except Exception:
                pass
        try:
            source.close()
        except Exception:
            pass
