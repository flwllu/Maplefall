import base64
import os
import re

from mutagen import File as MutagenFile
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TCOM, TDRC, TIT2, TPE1, TPE2, TCON, TRCK
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis

AUDIO_EXTENSIONS = {
    ".mp3", ".flac", ".m4a", ".wav", ".aiff", ".aif",
    ".ogg", ".opus", ".wma", ".aac",
}

TAG_KEYS = (
    "title", "artist", "album", "albumartist", "genre", "date",
    "tracknumber", "composer",
)

ID3_FRAMES = {
    "title": TIT2, "artist": TPE1, "album": TALB, "albumartist": TPE2,
    "genre": TCON, "date": TDRC, "tracknumber": TRCK, "composer": TCOM,
}

MP4_KEYS = {
    "title": "\xa9nam", "artist": "\xa9ART", "album": "\xa9alb",
    "albumartist": "aART", "genre": "\xa9gen", "date": "\xa9day",
    "composer": "\xa9wrt",
}

ASF_KEYS = {
    "title": "Title", "artist": "Author", "album": "WM/AlbumTitle",
    "albumartist": "WM/AlbumArtist", "genre": "WM/Genre",
    "date": "WM/Year", "tracknumber": "WM/TrackNumber",
    "composer": "WM/Composer",
}

ID3_SUFFIXES = {".mp3", ".wav", ".aiff", ".aif"}


def sanitize_filename(name):
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip().strip(".")
    reserved = {
        "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4",
        "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3",
        "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
    }
    if name.upper() in reserved:
        name = "_" + name
    return name[:160] or "unknown"


def get_metadata(file_path):
    meta = get_full_metadata(file_path)
    return meta["title"], meta["artist"]


def _first(value):
    if isinstance(value, (list, tuple)):
        return value[0] if value else None
    return value


def _read_easy(audio):
    result = {key: None for key in TAG_KEYS}
    tags = audio.tags
    if tags is None:
        return result
    for key in TAG_KEYS:
        try:
            value = tags.get(key)
        except Exception:
            value = None
        value = _first(value)
        if value is not None:
            result[key] = str(value)
    return result


def _read_id3(tags):
    result = {key: None for key in TAG_KEYS}
    if tags is None:
        return result
    for key, frame in ID3_FRAMES.items():
        try:
            value = tags.get(frame.__name__)
            if value is not None and getattr(value, "text", None):
                result[key] = str(value.text[0])
        except Exception:
            continue
    return result


def _read_asf(tags):
    result = {key: None for key in TAG_KEYS}
    if tags is None:
        return result
    for key, asf_key in ASF_KEYS.items():
        try:
            value = tags.get(asf_key)
            value = _first(value)
            if value is not None:
                result[key] = str(value)
        except Exception:
            continue
    return result


def get_all_metadata(file_path):
    """跨格式读取常见标签：MP3 / FLAC / M4A / OGG / WAV / AIFF / WMA。"""
    empty = {key: None for key in TAG_KEYS}
    try:
        from mutagen.asf import ASF

        audio = MutagenFile(file_path, easy=True)
        if audio is not None and audio.tags is not None:
            if isinstance(audio, ASF):
                return _read_asf(audio.tags)
            if isinstance(audio.tags, ID3):
                return _read_id3(audio.tags)

            result = _read_easy(audio)
            from mutagen.easymp4 import EasyMP4
            if isinstance(audio, (MP4, EasyMP4)):
                # EasyMP4 不暴露作曲等键，从原始原子补读
                raw = MutagenFile(file_path)
                raw_tags = raw.tags if raw is not None else None
                for key, mp4_key in MP4_KEYS.items():
                    if not result.get(key) and raw_tags is not None:
                        try:
                            value = _first(raw_tags.get(mp4_key))
                            if value is not None:
                                result[key] = str(value)
                        except Exception:
                            continue
            return result

        audio = MutagenFile(file_path)
        if audio is None:
            return empty
        if isinstance(audio, ASF):
            return _read_asf(audio.tags)
        if isinstance(audio.tags, ID3):
            return _read_id3(audio.tags)
        if audio.tags is not None:
            return _read_easy(audio)
    except Exception:
        pass
    return empty


def get_full_metadata(file_path):
    meta = get_all_metadata(file_path)
    return {
        "title": meta.get("title"),
        "artist": meta.get("artist"),
        "album": meta.get("album"),
    }


def format_file_size(path):
    size_bytes = os.path.getsize(path)
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


FORMAT_OPTIONS = {
    "artist_title": ("作者 - 歌曲名", "{artist} - {title}"),
    "title_artist": ("歌曲名 - 作者", "{title} - {artist}"),
    "title_only":  ("仅歌曲名",     "{title}"),
    "artist_only": ("仅作者名",     "{artist}"),
}

FORMAT_DEFAULT = "artist_title"


def generate_filename(title, artist, fmt=FORMAT_DEFAULT):
    if fmt not in FORMAT_OPTIONS:
        fmt = FORMAT_DEFAULT
    template = FORMAT_OPTIONS[fmt][1]

    name = template.replace("{title}", title or "")
    name = name.replace("{artist}", artist or "")
    name = name.strip(" -")

    if not name or name.isspace():
        return None
    return sanitize_filename(name)


def scan_folder(folder):
    results = []
    try:
        for name in os.listdir(folder):
            full = os.path.join(folder, name)
            if os.path.isfile(full):
                ext = os.path.splitext(name)[1].lower()
                if ext in AUDIO_EXTENSIONS:
                    results.append(full)
    except OSError:
        pass
    return results


# ===============================
#  音频属性
# ===============================

def get_audio_properties(file_path):
    try:
        audio = MutagenFile(file_path)
        if audio and audio.info:
            return {
                "length": audio.info.length,
                "bitrate": getattr(audio.info, "bitrate", 0),
                "sample_rate": getattr(audio.info, "sample_rate", 0),
                "channels": getattr(audio.info, "channels", 0),
                "encoder": getattr(audio.info, "encoder_info", ""),
            }
    except Exception:
        pass
    return {}


def format_duration(seconds):
    if seconds is None:
        return "--:--"
    total = int(seconds)
    hours, minutes = divmod(total, 3600)
    minutes, secs = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


# ===============================
#  封面
# ===============================

def _picture_entry(data, mime, picture_type=3):
    return {"mime": mime, "data": bytes(data), "type": picture_type}


def get_cover_art(file_path):
    results = []
    try:
        audio = MutagenFile(file_path)
        if audio is None:
            return results

        tags = audio.tags

        if isinstance(audio, FLAC) or isinstance(audio, OggVorbis):
            pictures = getattr(audio, "pictures", None)
            if pictures:
                for pic in pictures:
                    results.append(_picture_entry(
                        pic.data, pic.mime or "image/jpeg", pic.type))
                return results

            if tags is not None:
                for value in tags.get("metadata_block_picture", []) or []:
                    try:
                        pic = Picture(base64.b64decode(value))
                        results.append(_picture_entry(
                            pic.data, pic.mime or "image/jpeg", pic.type))
                    except Exception:
                        continue
                if results:
                    return results

        if isinstance(audio, MP4):
            covers = tags.get("covr") if tags else None
            for cover in covers or []:
                mime = "image/png" \
                    if bytes(cover[:8]) == b"\x89PNG\r\n\x1a\n" \
                    else "image/jpeg"
                results.append(_picture_entry(cover, mime))
            return results

        if isinstance(tags, ID3):
            for key in tags.keys():
                if str(key).startswith("APIC"):
                    apic = tags[key]
                    results.append(_picture_entry(
                        apic.data, apic.mime or "image/jpeg", apic.type))
    except Exception:
        pass
    return results


def _read_image(image_path):
    ext = os.path.splitext(image_path)[1].lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".bmp": "image/bmp", ".gif": "image/gif",
    }
    with open(image_path, "rb") as handle:
        return handle.read(), mime_map.get(ext, "image/jpeg")


def embed_cover_art(file_path, image_path):
    try:
        data, mime = _read_image(image_path)
        audio = MutagenFile(file_path)
        if audio is None:
            return False

        if isinstance(audio, FLAC):
            picture = Picture()
            picture.type = 3
            picture.mime = mime
            picture.desc = "Cover"
            picture.data = data
            audio.clear_pictures()
            audio.add_picture(picture)
            audio.save()
            return True

        if isinstance(audio, OggVorbis):
            picture = Picture()
            picture.type = 3
            picture.mime = mime
            picture.desc = "Cover"
            picture.data = data
            audio["metadata_block_picture"] = [
                base64.b64encode(picture.write()).decode("ascii")]
            audio.save()
            return True

        if isinstance(audio, MP4):
            if audio.tags is None:
                audio.add_tags()
            image_format = MP4Cover.FORMAT_PNG if mime == "image/png" \
                else MP4Cover.FORMAT_JPEG
            audio.tags["covr"] = [MP4Cover(data, imageformat=image_format)]
            audio.save()
            return True

        if audio.tags is None and \
                os.path.splitext(file_path)[1].lower() in ID3_SUFFIXES:
            audio.add_tags()
        tags = audio.tags
        if isinstance(tags, ID3):
            for key in list(tags.keys()):
                if str(key).startswith("APIC"):
                    del tags[key]
            tags["APIC"] = APIC(
                encoding=3, mime=mime, type=3, desc="Cover", data=data)
            audio.save()
            return True
    except Exception:
        return False
    return False


def remove_cover_art(file_path):
    try:
        audio = MutagenFile(file_path)
        if audio is None:
            return False

        if isinstance(audio, FLAC):
            if not audio.pictures:
                return False
            audio.clear_pictures()
            audio.save()
            return True

        if isinstance(audio, OggVorbis):
            tags = audio.tags
            if tags is None or "metadata_block_picture" not in tags:
                return False
            del tags["metadata_block_picture"]
            audio.save()
            return True

        if isinstance(audio, MP4):
            tags = audio.tags
            if tags is None or "covr" not in tags:
                return False
            del tags["covr"]
            audio.save()
            return True

        tags = audio.tags
        if isinstance(tags, ID3):
            removed = False
            for key in list(tags.keys()):
                if str(key).startswith("APIC"):
                    del tags[key]
                    removed = True
            if removed:
                audio.save()
                return True
    except Exception:
        pass
    return False


# ===============================
#  歌词
# ===============================

def get_lyrics(file_path):
    results = []
    try:
        audio = MutagenFile(file_path)
        tags = audio.tags if audio else None
        if isinstance(tags, ID3):
            for key in tags.keys():
                if str(key).startswith("USLT"):
                    uslt = tags[key]
                    results.append({
                        "lang": uslt.lang,
                        "desc": uslt.desc,
                        "text": uslt.text,
                    })
    except Exception:
        pass
    return results


# ===============================
#  写回元数据
# ===============================

def set_metadata(file_path, fields):
    """按容器类型写入标签，返回是否成功。"""
    try:
        audio = MutagenFile(file_path)
        if audio is None:
            return False

        suffix = os.path.splitext(file_path)[1].lower()

        if isinstance(audio, MP4):
            if audio.tags is None:
                audio.add_tags()
            for key, value in fields.items():
                try:
                    if key == "tracknumber":
                        number = int(str(value).split("/")[0])
                        audio["trkn"] = [(number, 0)]
                    elif key in MP4_KEYS:
                        audio[MP4_KEYS[key]] = [value]
                except Exception:
                    continue
            audio.save()
            return True

        if isinstance(audio.tags, ID3) or \
                (audio.tags is None and suffix in ID3_SUFFIXES):
            if audio.tags is None:
                audio.add_tags()
            tags = audio.tags
            for key, value in fields.items():
                frame_class = ID3_FRAMES.get(key)
                if frame_class is None:
                    continue
                tags.delall(frame_class.__name__)
                tags.add(frame_class(encoding=3, text=[value]))
            audio.save()
            return True

        from mutagen.asf import ASF
        if isinstance(audio, ASF):
            if audio.tags is None:
                audio.add_tags()
            for key, value in fields.items():
                asf_key = ASF_KEYS.get(key)
                if asf_key:
                    try:
                        audio[asf_key] = [value]
                    except Exception:
                        continue
            audio.save()
            return True

        if audio.tags is None:
            audio.add_tags()
        for key, value in fields.items():
            try:
                audio[key] = [value]
            except Exception:
                continue
        audio.save()
        return True
    except Exception:
        return False


# ===============================
#  从 JSON 导入元数据
# ===============================

def import_metadata_from_json(file_path, json_path):
    import json
    try:
        with open(json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return False

    fields = {}
    for key in TAG_KEYS:
        if key in data and data[key] is not None:
            fields[key] = str(data[key])

    return set_metadata(file_path, fields) if fields else False
