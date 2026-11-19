//! MDX-Net vocal separation (UVR compatible).
//!
//! Runs an MDX-Net ONNX model against an audio file, then derives the vocal
//! stem by subtracting the instrumental output from the mix (same trick UVR
//! uses for "Instrumental Only" models).
//!
//! The model is bundled under `resources/models/` and read from the app's
//! resource directory. `UVR_MODEL_PATH` overrides it, and as a last resort the
//! model is taken from the user's Ultimate Vocal Remover installation.

use std::f32::consts::PI;
use std::path::{Path, PathBuf};

use hound::{SampleFormat, WavSpec, WavWriter};
use ort::value::Tensor;
use realfft::{ComplexToReal, RealFftPlanner, RealToComplex};
use symphonia::core::audio::SampleBuffer;
use symphonia::core::codecs::{DecoderOptions, CODEC_TYPE_NULL};
use symphonia::core::errors::Error as SymError;
use symphonia::core::formats::FormatOptions;
use symphonia::core::io::MediaSourceStream;
use symphonia::core::meta::MetadataOptions;
use symphonia::core::probe::Hint;

const N_FFT: usize = 6144;
const HOP: usize = 1024;
const DIM_F: usize = 3072;
const FRAMES: usize = 256;
const CHUNK: usize = HOP * (FRAMES - 1);
const TRIM: usize = N_FFT / 2;
const GEN: usize = CHUNK - 2 * TRIM;
const SAMPLE_RATE: u32 = 44100;
const OVERLAP: f32 = 0.25;

/// 随包分发的模型文件名（位于 `resources/models/` 下）。
const MODEL_FILE: &str = "UVR-MDX-NET-Inst_HQ_3.onnx";
/// 旧版回退路径：用户本机装过的 UVR 自带的同一模型。
const MODEL_REL: &str = "Contents/Resources/models/MDX_Net_Models/UVR-MDX-NET-Inst_HQ_3.onnx";

/// 用源文件名生成可读的缓存名：`歌名 - vocals - 短哈希.wav`，
/// 短哈希保证同名不同文件不会互相覆盖。
pub fn cache_file_name(input: &Path, suffix: &str, key: &str) -> String {
    let stem = input
        .file_stem()
        .and_then(|s| s.to_str())
        .unwrap_or("audio");
    let safe: String = stem
        .chars()
        .map(|c| if "/\\:*?\"<>|".contains(c) { '_' } else { c })
        .take(60)
        .collect();
    let short = &key[..key.len().min(8)];
    format!("{safe} - {suffix} - {short}.wav")
}

/// 定位 MDX 模型，优先级：`UVR_MODEL_PATH` 覆盖 > 随包资源 > 本机 UVR 安装。
pub fn model_path(resources: Option<&Path>) -> Option<PathBuf> {
    if let Ok(value) = std::env::var("UVR_MODEL_PATH") {
        if !value.trim().is_empty() {
            let path = PathBuf::from(value);
            if path.exists() {
                return Some(path);
            }
        }
    }
    if let Some(root) = resources {
        let bundled = root.join("models").join(MODEL_FILE);
        if bundled.exists() {
            return Some(bundled);
        }
    }
    // 本机 UVR 安装目录这条回退只在 macOS 上有意义，其它平台直接跳过。
    if cfg!(target_os = "macos") {
        let fallback = PathBuf::from("/Applications/Ultimate Vocal Remover.app").join(MODEL_REL);
        if fallback.exists() {
            return Some(fallback);
        }
    }
    None
}

pub fn separate_vocals(
    model: &Path,
    input: &Path,
    output: &Path,
    progress: &mut dyn FnMut(u32),
    cancelled: &dyn Fn() -> bool,
) -> Result<(), String> {
    progress(0);
    let (mut left, mut right, rate) = decode_stereo(input)?;
    if rate != SAMPLE_RATE {
        left = resample_linear(&left, rate, SAMPLE_RATE);
        right = resample_linear(&right, rate, SAMPLE_RATE);
    }
    if left.is_empty() {
        return Err("音频是空的".into());
    }
    if cancelled() {
        return Err("已停止".into());
    }

    let peak = left
        .iter()
        .chain(right.iter())
        .fold(0f32, |acc, v| acc.max(v.abs()));
    let gain = if peak > 0.0 { 0.9 / peak } else { 1.0 };
    for v in left.iter_mut().chain(right.iter_mut()) {
        *v *= gain;
    }

    let n = left.len();
    let instrumental = demix(model, &left, &right, progress, cancelled)?;

    progress(96);
    let spec = WavSpec {
        channels: 1,
        sample_rate: SAMPLE_RATE,
        bits_per_sample: 16,
        sample_format: SampleFormat::Int,
    };
    let mut vocals = Vec::with_capacity(n);
    for i in 0..n {
        // Vocals = mix - instrumental, mono downmix for whisper.
        vocals.push((0.5 * (left[i] + right[i]) - instrumental[i]) / gain);
    }
    let vocal_peak = vocals.iter().fold(0f32, |acc, v| acc.max(v.abs()));
    let scale = if vocal_peak > 0.99 { 0.9 / vocal_peak } else { 1.0 };

    let mut writer =
        WavWriter::create(output, spec).map_err(|e| format!("写入分离结果失败: {e}"))?;
    for value in &vocals {
        let sample = (value * scale).clamp(-1.0, 1.0);
        writer
            .write_sample((sample * 32767.0) as i16)
            .map_err(|e| format!("写入分离结果失败: {e}"))?;
    }
    writer.finalize().map_err(|e| e.to_string())?;
    progress(100);
    Ok(())
}

/// 估算音频时长（秒），优先用容器里的帧数，拿不到再解码统计。
pub fn audio_duration_secs(path: &Path) -> Result<f64, String> {
    let file = std::fs::File::open(path).map_err(|e| format!("打开音频失败: {e}"))?;
    let mss = MediaSourceStream::new(Box::new(file), Default::default());
    let mut hint = Hint::new();
    if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
        hint.with_extension(ext);
    }
    let probed = symphonia::default::get_probe()
        .format(
            &hint,
            mss,
            &FormatOptions {
                enable_gapless: true,
                ..Default::default()
            },
            &MetadataOptions::default(),
        )
        .map_err(|e| format!("无法识别音频格式: {e}"))?;
    let mut format = probed.format;
    let track = format
        .tracks()
        .iter()
        .find(|t| t.codec_params.codec != CODEC_TYPE_NULL)
        .ok_or("音频里没有可解码的音轨")?;
    let track_id = track.id;
    let rate = track.codec_params.sample_rate.unwrap_or(SAMPLE_RATE).max(1);
    if let Some(frames) = track.codec_params.n_frames {
        return Ok(frames as f64 / rate as f64);
    }

    let mut decoder = symphonia::default::get_codecs()
        .make(&track.codec_params, &DecoderOptions::default())
        .map_err(|e| format!("创建解码器失败: {e}"))?;
    let mut frames: u64 = 0;
    loop {
        let packet = match format.next_packet() {
            Ok(p) => p,
            Err(SymError::IoError(e)) if e.kind() == std::io::ErrorKind::UnexpectedEof => break,
            Err(SymError::ResetRequired) => break,
            Err(e) => return Err(format!("读取音频失败: {e}")),
        };
        if packet.track_id() != track_id {
            continue;
        }
        match decoder.decode(&packet) {
            Ok(decoded) => frames += decoded.frames() as u64,
            Err(SymError::DecodeError(_)) => continue,
            Err(e) => return Err(format!("解码失败: {e}")),
        }
    }
    Ok(frames as f64 / rate as f64)
}

fn decode_stereo(path: &Path) -> Result<(Vec<f32>, Vec<f32>, u32), String> {    let file = std::fs::File::open(path).map_err(|e| format!("打开音频失败: {e}"))?;
    let mss = MediaSourceStream::new(Box::new(file), Default::default());
    let mut hint = Hint::new();
    if let Some(ext) = path.extension().and_then(|e| e.to_str()) {
        hint.with_extension(ext);
    }
    let probed = symphonia::default::get_probe()
        .format(
            &hint,
            mss,
            &FormatOptions {
                enable_gapless: true,
                ..Default::default()
            },
            &MetadataOptions::default(),
        )
        .map_err(|e| format!("无法识别音频格式: {e}"))?;
    let mut format = probed.format;
    let track = format
        .tracks()
        .iter()
        .find(|t| t.codec_params.codec != CODEC_TYPE_NULL)
        .ok_or("音频里没有可解码的音轨")?;
    let track_id = track.id;
    let rate = track.codec_params.sample_rate.unwrap_or(SAMPLE_RATE);
    let mut decoder = symphonia::default::get_codecs()
        .make(&track.codec_params, &DecoderOptions::default())
        .map_err(|e| format!("创建解码器失败: {e}"))?;

    let mut left: Vec<f32> = Vec::new();
    let mut right: Vec<f32> = Vec::new();
    loop {
        let packet = match format.next_packet() {
            Ok(p) => p,
            Err(SymError::IoError(e)) if e.kind() == std::io::ErrorKind::UnexpectedEof => break,
            Err(SymError::ResetRequired) => break,
            Err(e) => return Err(format!("读取音频失败: {e}")),
        };
        if packet.track_id() != track_id {
            continue;
        }
        let decoded = match decoder.decode(&packet) {
            Ok(d) => d,
            Err(SymError::DecodeError(_)) => continue,
            Err(e) => return Err(format!("解码失败: {e}")),
        };
        let spec = *decoded.spec();
        let channels = spec.channels.count().max(1);
        let mut buf = SampleBuffer::<f32>::new(decoded.capacity() as u64, spec);
        buf.copy_interleaved_ref(decoded);
        let samples = buf.samples();
        for frame in samples.chunks_exact(channels) {
            left.push(frame[0]);
            right.push(if channels > 1 { frame[1] } else { frame[0] });
        }
    }
    Ok((left, right, rate))
}

fn resample_linear(input: &[f32], from: u32, to: u32) -> Vec<f32> {
    if from == to || input.is_empty() {
        return input.to_vec();
    }
    let ratio = to as f64 / from as f64;
    let out_len = ((input.len() as f64) * ratio).round() as usize;
    let mut out = Vec::with_capacity(out_len);
    for i in 0..out_len {
        let pos = i as f64 / ratio;
        let idx = pos.floor() as usize;
        let frac = (pos - idx as f64) as f32;
        let a = input[idx.min(input.len() - 1)];
        let b = input[(idx + 1).min(input.len() - 1)];
        out.push(a + (b - a) * frac);
    }
    out
}

fn hann_periodic(n: usize) -> Vec<f32> {
    (0..n)
        .map(|i| 0.5 - 0.5 * (2.0 * PI * i as f32 / n as f32).cos())
        .collect()
}

fn hann_symmetric(n: usize) -> Vec<f32> {
    if n <= 1 {
        return vec![1.0];
    }
    (0..n)
        .map(|i| 0.5 - 0.5 * (2.0 * PI * i as f32 / (n as f32 - 1.0)).cos())
        .collect()
}

fn reflect_pad(x: &[f32], pad: usize) -> Vec<f32> {
    let n = x.len();
    let mut out = vec![0f32; n + pad * 2];
    out[pad..pad + n].copy_from_slice(x);
    for i in 0..pad {
        out[i] = x[pad - i];
        out[pad + n + i] = x[n - 2 - i];
    }
    out
}

fn stft(
    padded_l: &[f32],
    padded_r: &[f32],
    window: &[f32],
    r2c: &dyn RealToComplex<f32>,
    spec: &mut [f32],
) {
    let mut input = r2c.make_input_vec();
    let mut output = r2c.make_output_vec();
    for (c, padded) in [padded_l, padded_r].into_iter().enumerate() {
        for t in 0..FRAMES {
            let start = t * HOP;
            for (i, slot) in input.iter_mut().enumerate() {
                *slot = padded[start + i] * window[i];
            }
            r2c.process(&mut input, &mut output)
                .expect("forward fft failed");
            for bin in 0..DIM_F {
                let base = ((c * 2) * DIM_F + bin) * FRAMES + t;
                if bin < 3 {
                    spec[base] = 0.0;
                    spec[base + DIM_F * FRAMES] = 0.0;
                } else {
                    spec[base] = output[bin].re;
                    spec[base + DIM_F * FRAMES] = output[bin].im;
                }
            }
        }
    }
}

fn istft(
    spec: &[f32],
    window: &[f32],
    c2r: &dyn ComplexToReal<f32>,
    out_l: &mut [f32],
    out_r: &mut [f32],
) {
    let full_len = CHUNK + 2 * TRIM;
    let mut spectrum = c2r.make_input_vec();
    let mut output = c2r.make_output_vec();
    let mut env = vec![0f32; full_len];
    // realfft follows RustFFT and does not normalize the inverse transform.
    let inv = 1.0 / N_FFT as f32;

    for (c, out) in [out_l, out_r].into_iter().enumerate() {
        let acc = out;
        acc[..full_len].fill(0.0);
        env.fill(0.0);
        for t in 0..FRAMES {
            spectrum[DIM_F] = Default::default();
            for bin in 3..DIM_F {
                let base = ((c * 2) * DIM_F + bin) * FRAMES + t;
                spectrum[bin].re = spec[base];
                spectrum[bin].im = spec[base + DIM_F * FRAMES];
            }
            for bin in 0..3 {
                spectrum[bin] = Default::default();
            }
            c2r.process(&mut spectrum, &mut output)
                .expect("inverse fft failed");
            let start = t * HOP;
            for (i, sample) in output.iter().enumerate() {
                acc[start + i] += sample * inv * window[i];
                env[start + i] += window[i] * window[i];
            }
        }
        for i in 0..CHUNK {
            let e = env[TRIM + i];
            acc[i] = if e > 1e-11 { acc[TRIM + i] / e } else { 0.0 };
        }
    }
}

fn demix(
    model: &Path,
    left: &[f32],
    right: &[f32],
    progress: &mut dyn FnMut(u32),
    cancelled: &dyn Fn() -> bool,
) -> Result<Vec<f32>, String> {
    let env = ort::init()
        .build()
        .map_err(|e| format!("初始化 ONNX Runtime 失败: {e}"))?;
    let mut builder = ort::session::Session::builder(&env)
        .map_err(|e| format!("创建推理会话失败: {e}"))?;
    let mut session = builder
        .commit_from_file(model)
        .map_err(|e| format!("加载 MDX 模型失败: {e}"))?;

    let mut planner = RealFftPlanner::<f32>::new();
    let r2c = planner.plan_fft_forward(N_FFT);
    let c2r = planner.plan_fft_inverse(N_FFT);
    let window = hann_periodic(N_FFT);

    let n = left.len();
    let pad = GEN + TRIM - (n % GEN);
    let total = n + TRIM + pad;
    let step = ((1.0 - OVERLAP) * CHUNK as f32) as usize;

    let mut result = vec![0f32; total];
    let mut divider = vec![0f32; total];
    let mut spec = vec![0f32; 4 * DIM_F * FRAMES];
    let mut chunk_l = vec![0f32; CHUNK];
    let mut chunk_r = vec![0f32; CHUNK];
    let mut out_l = vec![0f32; CHUNK + 2 * TRIM];
    let mut out_r = vec![0f32; CHUNK + 2 * TRIM];

    let mut start = 0;
    while start < total {
        if cancelled() {
            return Err("已停止".into());
        }
        let end = (start + CHUNK).min(total);
        let actual = end - start;
        chunk_l.iter_mut().for_each(|v| *v = 0.0);
        chunk_r.iter_mut().for_each(|v| *v = 0.0);

        for i in 0..actual {
            let src = start + i;
            if src < TRIM {
                chunk_l[i] = 0.0;
                chunk_r[i] = 0.0;
            } else if src - TRIM < n {
                chunk_l[i] = left[src - TRIM];
                chunk_r[i] = right[src - TRIM];
            }
        }

        let padded_l = reflect_pad(&chunk_l, TRIM);
        let padded_r = reflect_pad(&chunk_r, TRIM);
        stft(&padded_l, &padded_r, &window, r2c.as_ref(), &mut spec);

        let input = Tensor::from_array((
            [1i64, 4, DIM_F as i64, FRAMES as i64],
            spec.clone(),
        ))
        .map_err(|e| format!("构建输入张量失败: {e}"))?;
        let outputs = session
            .run(ort::inputs!["input" => input])
            .map_err(|e| format!("MDX 推理失败: {e}"))?;
        let (_shape, data) = outputs[0]
            .try_extract_tensor::<f32>()
            .map_err(|e| format!("读取模型输出失败: {e}"))?;
        if data.len() != spec.len() {
            return Err(format!("模型输出尺寸不符: {}", data.len()));
        }
        spec.copy_from_slice(data);

        istft(&spec, &window, c2r.as_ref(), &mut out_l, &mut out_r);

        let blend = hann_symmetric(actual);
        for i in 0..actual {
            result[start + i] += out_l[i] * blend[i];
            divider[start + i] += blend[i];
        }

        start += step;
        let percent = 5 + (start.min(total) as u64 * 88 / total as u64) as u32;
        progress(percent.min(93));
    }

    let mut instrumental = vec![0f32; total];
    for i in 0..total {
        instrumental[i] = if divider[i] > 1e-8 {
            result[i] / divider[i]
        } else {
            0.0
        };
    }

    let mut mono = vec![0f32; n];
    mono.copy_from_slice(&instrumental[TRIM..TRIM + n]);
    Ok(mono)
}
