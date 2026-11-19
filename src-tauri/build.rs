fn main() {
    link_clang_runtime_on_macos();
    tauri_build::build()
}

/// ort 随附的静态 onnxruntime 引用了 `___isPlatformVersionAtLeast`，该符号由 clang
/// 运行时提供。release（fat LTO）链接时 clang 驱动不会自动带上它，需要显式链接。
/// 运行时库路径按本机 clang 的 resource dir 解析，不写死任何绝对路径。
fn link_clang_runtime_on_macos() {
    if std::env::var("CARGO_CFG_TARGET_OS").as_deref() != Ok("macos") {
        return;
    }
    let output = match std::process::Command::new("clang")
        .arg("--print-resource-dir")
        .output()
    {
        Ok(output) if output.status.success() => output,
        _ => return,
    };
    let dir = String::from_utf8_lossy(&output.stdout).trim().to_string();
    if dir.is_empty() {
        return;
    }
    let lib = format!("{dir}/lib/darwin/libclang_rt.osx.a");
    if std::path::Path::new(&lib).exists() {
        println!("cargo:rustc-link-arg={lib}");
    }
}
