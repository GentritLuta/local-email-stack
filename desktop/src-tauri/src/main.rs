// LocalEmailStack desktop — main entry.
// All actual Tauri setup lives in lib.rs so cargo test/bench can reuse it.

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

fn main() {
    local_email_stack_lib::run();
}
