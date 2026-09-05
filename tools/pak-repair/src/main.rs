//! Private worker. The Python service validates indexes and stages/backups files.
//! Never invoke this worker on a live package; output must be a new file.
use std::{fs::{File, OpenOptions}, io::{BufReader, Seek}, path::Path};

fn unsupported(mount: &str, entry: &str) -> bool {
    let mount = mount.replace('\\', "/");
    let entry = entry.replace('\\', "/");
    let full = if entry.starts_with("../../../") { entry } else {
        format!("{}/{}", mount.trim_end_matches('/'), entry.trim_start_matches('/'))
    };
    full.eq_ignore_ascii_case("../../../chunknames")
        || full.eq_ignore_ascii_case("../../../patched_files")
        // Use a filename match, so a valid desktop.ini.uasset is preserved.
        || full.rsplit('/').next().unwrap_or("").eq_ignore_ascii_case("desktop.ini")
}

fn repair(input: &Path, output: &Path) -> Result<(), Box<dyn std::error::Error>> {
    let key = "0C263D8C22DCB085894899C3A3796383E9BF9DE0CBFB08C9BF2DEF2E84F29D74"
        .parse::<repak::utils::AesKey>()?.0;
    let reader = repak::PakBuilder::new().key(key)
        .reader(&mut BufReader::new(File::open(input)?))?;
    let removed: Vec<_> = reader.files().into_iter()
        .filter(|entry| unsupported(reader.mount_point(), entry)).collect();
    let mut file = OpenOptions::new().write(true).read(true).create_new(true).open(output)?;
    std::io::copy(&mut File::open(input)?, &mut file)?;
    if !removed.is_empty() {
        let mut writer = reader.into_pakwriter(&mut file)?;
        for entry in removed { writer.remove_entry(&entry); }
        let file = writer.write_index()?;
        let len = file.stream_position()?;
        file.set_len(len)?;
    }
    file.sync_all()?;
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 2 { return Err("Expected input and new output paths".into()); }
    repair(Path::new(&args[0]), Path::new(&args[1]))
}
