"""Universal Media Analyzer for Video, Audio, and Image assets."""

from __future__ import annotations
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Tuple

from vcx.diff.analyzers.base import AnalysisResult, BaseAnalyzer


class MediaAnalyzer(BaseAnalyzer):
    """Analyzes multimedia streams (Video, Audio, Images) extracting codecs, resolutions, and stream properties."""

    def analyze(
        self,
        old_content: Optional[bytes],
        new_content: Optional[bytes],
        file_name: str,
    ) -> AnalysisResult:
        old_meta = self._extract_media_meta(old_content, file_name)
        new_meta = self._extract_media_meta(new_content, file_name)

        domain_facts, raw_diff, vision_summary = self._compute_media_delta(
            old_meta, new_meta, file_name
        )

        return AnalysisResult(
            previous_metadata=old_meta,
            current_metadata=new_meta,
            raw_diff=raw_diff,
            vision_summary=vision_summary,
            domain_facts=domain_facts,
        )

    def _extract_media_meta(self, content: Optional[bytes], file_name: str) -> Dict[str, Any]:
        meta: Dict[str, Any] = {
            "file_size": len(content) if content else 0,
            "media_type": "unknown",
        }
        if not content:
            return meta

        lower = file_name.lower()

        # Image analysis via Pillow
        if lower.endswith((".png", ".jpg", ".jpeg", ".webp", ".svg", ".gif", ".bmp", ".tiff", ".tif", ".ico")):
            meta.update(self._parse_image(content, lower))
            return meta

        # Try ffprobe for video/audio if available
        if shutil.which("ffprobe"):
            ffprobe_meta = self._probe_with_ffprobe(content, lower)
            if ffprobe_meta:
                meta.update(ffprobe_meta)

        # Supplement with native binary parsers for formats where headers have explicit properties
        if lower.endswith((".wav", ".wave")):
            wav_h = self._parse_wav_header(content)
            for k, v in wav_h.items():
                if meta.get(k) is None:
                    meta[k] = v
        elif lower.endswith((".flac",)):
            flac_h = self._parse_flac_header(content)
            for k, v in flac_h.items():
                if meta.get(k) is None:
                    meta[k] = v
        elif lower.endswith((".mp4", ".mov", ".m4v")):
            mp4_h = self._parse_mp4_header(content)
            for k, v in mp4_h.items():
                if meta.get(k) is None:
                    meta[k] = v
        elif lower.endswith((".mp3",)):
            mp3_h = self._parse_mp3_header(content)
            for k, v in mp3_h.items():
                if meta.get(k) is None:
                    meta[k] = v

        return meta

    def _probe_with_ffprobe(self, content: bytes, file_name: str) -> Optional[Dict[str, Any]]:
        tmp_path = None
        try:
            suffix = Path(file_name).suffix or ".bin"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(content)
                tmp_path = tmp.name

            cmd = [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format", "-show_streams",
                tmp_path
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if proc.returncode != 0 or not proc.stdout.strip():
                return None

            data = json.loads(proc.stdout)
            streams = data.get("streams", [])
            fmt = data.get("format", {})

            result: Dict[str, Any] = {
                "duration_seconds": round(float(fmt.get("duration", 0)), 2),
                "bitrate_kbps": int(fmt.get("bit_rate", 0)) // 1000 if fmt.get("bit_rate") else None,
            }

            video_streams = [s for s in streams if s.get("codec_type") == "video"]
            audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

            if video_streams:
                v = video_streams[0]
                result["media_type"] = "video"
                result["video_codec"] = v.get("codec_name")
                result["width"] = v.get("width")
                result["height"] = v.get("height")
                fps_eval = v.get("r_frame_rate", "0/1")
                try:
                    num, den = map(float, fps_eval.split("/"))
                    result["fps"] = round(num / den, 2) if den > 0 else 0.0
                except Exception:
                    result["fps"] = None

            if audio_streams:
                a = audio_streams[0]
                if "media_type" not in result or result["media_type"] == "unknown":
                    result["media_type"] = "audio"
                result["audio_codec"] = a.get("codec_name")
                result["sample_rate_hz"] = int(a.get("sample_rate", 0)) if a.get("sample_rate") else None
                result["channels"] = a.get("channels")
                result["channel_layout"] = a.get("channel_layout")
                raw_bits = a.get("bits_per_raw_sample") or a.get("bits_per_sample")
                if raw_bits:
                    try:
                        result["bit_depth"] = int(raw_bits)
                    except (ValueError, TypeError):
                        pass

            return result
        except Exception:
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _parse_image(self, content: bytes, file_name: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {"media_type": "image"}
        if file_name.endswith(".svg"):
            import xml.etree.ElementTree as ET
            try:
                root = ET.fromstring(content.decode("utf-8", errors="ignore"))
                result["format"] = "SVG"
                result["width"] = root.attrib.get("width")
                result["height"] = root.attrib.get("height")
                result["viewBox"] = root.attrib.get("viewBox")
                result["paths_count"] = len(root.findall(".//{http://www.w3.org/2000/svg}path")) + len(root.findall(".//path"))
                return result
            except Exception:
                return result

        try:
            from PIL import Image
            with Image.open(io.BytesIO(content)) as im:
                result["format"] = im.format
                result["width"] = im.width
                result["height"] = im.height
                result["mode"] = im.mode
                result["is_animated"] = getattr(im, "is_animated", False)
                result["frame_count"] = getattr(im, "n_frames", 1)
        except Exception:
            pass
        return result

    def _parse_wav_header(self, content: bytes) -> Dict[str, Any]:
        result: Dict[str, Any] = {"media_type": "audio", "audio_codec": "pcm"}
        if len(content) >= 36 and content[:4] == b"RIFF" and content[8:12] == b"WAVE":
            try:
                channels = struct.unpack_from("<H", content, 22)[0]
                sample_rate = struct.unpack_from("<I", content, 24)[0]
                bits_per_sample = struct.unpack_from("<H", content, 34)[0]
                result["channels"] = channels
                result["sample_rate_hz"] = sample_rate
                result["bit_depth"] = bits_per_sample
                data_size = len(content) - 44
                if channels > 0 and sample_rate > 0 and bits_per_sample > 0:
                    bytes_per_sec = sample_rate * channels * (bits_per_sample // 8)
                    if bytes_per_sec > 0:
                        result["duration_seconds"] = round(data_size / bytes_per_sec, 2)
            except Exception:
                pass
        return result

    def _parse_flac_header(self, content: bytes) -> Dict[str, Any]:
        result: Dict[str, Any] = {"media_type": "audio", "audio_codec": "flac"}
        if len(content) >= 26 and content.startswith(b"fLaC"):
            try:
                # STREAMINFO metadata block starts at byte 8
                block = content[8:42]
                sample_rate = (block[10] << 12) | (block[11] << 4) | (block[12] >> 4)
                channels = ((block[12] >> 1) & 0x07) + 1
                bits_per_sample = (((block[12] & 0x01) << 4) | (block[13] >> 4)) + 1
                result["sample_rate_hz"] = sample_rate
                result["channels"] = channels
                result["bit_depth"] = bits_per_sample
            except Exception:
                pass
        return result

    def _parse_mp3_header(self, content: bytes) -> Dict[str, Any]:
        return {"media_type": "audio", "audio_codec": "mp3"}

    def _parse_mp4_header(self, content: bytes) -> Dict[str, Any]:
        return {"media_type": "video", "container": "mp4/mov"}

    def _compute_media_delta(
        self, old_meta: Dict[str, Any], new_meta: Dict[str, Any], file_name: str
    ) -> Tuple[Dict[str, Any], str, str]:
        facts: Dict[str, Any] = {"media_deltas": []}
        diff_lines: List[str] = []
        vision_parts: List[str] = []

        m_type = new_meta.get("media_type") or old_meta.get("media_type") or "media"

        # Resolution / Dimensions
        o_w, o_h = old_meta.get("width"), old_meta.get("height")
        n_w, n_h = new_meta.get("width"), new_meta.get("height")
        if n_w and n_h:
            curr_res = f"{n_w}x{n_h}"
            if o_w and o_h and (o_w != n_w or o_h != n_h):
                facts["media_deltas"].append(f"Resolution changed from {o_w}x{o_h} to {curr_res}")
                diff_lines.append(f"- resolution: {o_w}x{o_h}")
                diff_lines.append(f"+ resolution: {curr_res}")
                vision_parts.append(f"Visual resolution scaled from {o_w}x{o_h} to {curr_res}")
            else:
                diff_lines.append(f"+ resolution: {curr_res}")
                vision_parts.append(f"Resolution: {curr_res}")

        # Framerate
        o_fps, n_fps = old_meta.get("fps"), new_meta.get("fps")
        if n_fps:
            if o_fps and o_fps != n_fps:
                facts["media_deltas"].append(f"Framerate adjusted: {o_fps} fps -> {n_fps} fps")
                diff_lines.append(f"- fps: {o_fps}")
                diff_lines.append(f"+ fps: {n_fps}")
                vision_parts.append(f"Timeline playback rate: {n_fps} fps")
            else:
                diff_lines.append(f"+ fps: {n_fps}")

        # Duration
        o_dur, n_dur = old_meta.get("duration_seconds"), new_meta.get("duration_seconds")
        if n_dur is not None:
            if o_dur is not None and o_dur != n_dur:
                d_delta = round(n_dur - o_dur, 2)
                facts["media_deltas"].append(f"Duration changed: {o_dur}s -> {n_dur}s ({d_delta:+0.2f}s)")
                diff_lines.append(f"- duration: {o_dur}s")
                diff_lines.append(f"+ duration: {n_dur}s ({d_delta:+0.2f}s)")
                vision_parts.append(f"Duration delta: {d_delta:+0.2f}s (Total: {n_dur}s)")
            else:
                diff_lines.append(f"+ duration: {n_dur}s")

        # Audio Stream Details
        n_sr = new_meta.get("sample_rate_hz")
        o_sr = old_meta.get("sample_rate_hz")
        if n_sr:
            if o_sr and o_sr != n_sr:
                facts["media_deltas"].append(f"Audio sample rate resampled: {o_sr}Hz -> {n_sr}Hz")
                diff_lines.append(f"- sample_rate: {o_sr}Hz")
                diff_lines.append(f"+ sample_rate: {n_sr}Hz")
                vision_parts.append(f"Sample rate: {n_sr}Hz")
            else:
                diff_lines.append(f"+ sample_rate: {n_sr}Hz")

        n_ch = new_meta.get("channels")
        o_ch = old_meta.get("channels")
        if n_ch:
            layout_label = "Mono" if n_ch == 1 else ("Stereo" if n_ch == 2 else f"{n_ch}-Channel")
            if o_ch and o_ch != n_ch:
                facts["media_deltas"].append(f"Audio channel layout shifted: {o_ch} -> {n_ch} ({layout_label})")
                diff_lines.append(f"- channels: {o_ch}")
                diff_lines.append(f"+ channels: {n_ch} ({layout_label})")
            else:
                diff_lines.append(f"+ audio_layout: {layout_label}")

        # Codec Shifts
        if new_meta.get("video_codec") and new_meta.get("video_codec") != old_meta.get("video_codec"):
            facts["media_deltas"].append(f"Video codec: {new_meta.get('video_codec')}")
            diff_lines.append(f"+ video_codec: {new_meta.get('video_codec')}")

        if new_meta.get("audio_codec") and new_meta.get("audio_codec") != old_meta.get("audio_codec"):
            facts["media_deltas"].append(f"Audio codec: {new_meta.get('audio_codec')}")
            diff_lines.append(f"+ audio_codec: {new_meta.get('audio_codec')}")

        # File size
        s_delta = new_meta.get("file_size", 0) - old_meta.get("file_size", 0)
        if s_delta != 0:
            facts["media_deltas"].append(f"Media asset payload size delta: {s_delta:+d} bytes")
            diff_lines.append(f"+ file_size: {new_meta.get('file_size', 0)} ({s_delta:+d} bytes)")

        raw_diff = "\n".join(diff_lines) if diff_lines else f"{m_type.capitalize()} stream updated ({new_meta.get('file_size', 0)} bytes)"
        vision_summary = "; ".join(vision_parts) if vision_parts else f"Multimodal media inspection verified {m_type} stream."

        return facts, raw_diff, vision_summary
